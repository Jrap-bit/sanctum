import asyncio
import json
import time
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from ..core.cache import get_redis, job_channel, read_job_state
from ..core.config import get_settings
from ..core.database import SessionLocal
from ..core.security import COOKIE_NAME
from ..db.models import ExtractionJob, StoredDocument, SummaryJob, User
from ..services.authorization import has_access
from ..services.session_store import consume_ws_ticket, read_session
from .deps import Db


router = APIRouter()


@router.websocket("/api/v1/ws/jobs/{job_id}")
async def job_progress_ws(websocket: WebSocket, job_id: str, db: Db):
    settings = get_settings()
    allowed = set(settings.allowed_origins) | {settings.allowed_origin}
    origin = websocket.headers.get("origin")
    if origin not in allowed:
        await websocket.close(code=4403)
        return

    cookie = websocket.cookies.get(COOKIE_NAME)
    user_id = read_session(cookie) if cookie else None
    if not user_id:
        ticket = websocket.query_params.get("ticket")
        user_id = consume_ws_ticket(ticket) if ticket else None

    if not user_id:
        await websocket.close(code=4401)
        return

    user = db.get(User, user_id)
    if not user or not user.active or not user.credentials_ready or user.password_reset_required:
        await websocket.close(code=4401)
        return

    job = db.get(ExtractionJob, str(job_id))
    patient_id = None
    doc_page_count = 1
    if job:
        doc = db.get(StoredDocument, job.document_id)
        if doc:
            patient_id = doc.patient_id
            doc_page_count = doc.page_count
    else:
        sjob = db.get(SummaryJob, str(job_id))
        if sjob:
            job = sjob
            patient_id = sjob.patient_id

    if not job or not patient_id:
        await websocket.close(code=4404)
        return

    caps = getattr(user, "capabilities", []) or []
    if "clinical:read" not in caps or not has_access(db, user, patient_id):
        await websocket.close(code=4404)
        return

    db.close()
    await websocket.accept()

    state = read_job_state(str(job_id))
    if not state:
        if isinstance(job, ExtractionJob):
            progress = int(job.completed_pages * 100 / doc_page_count) if doc_page_count else 0
        else:
            progress = 100 if job.state == "completed" else 0
        state = {
            "jobId": str(job.id),
            "state": job.state,
            "progress": progress,
            "stage": None,
            "message": job.message,
        }

    # A re-queued job can leave a finished state behind in Redis; the database decides.
    terminal = {"completed", "failed", "cancelled"}
    if state.get("state") in terminal and job.state not in terminal:
        state = {"jobId": str(job.id), "state": job.state, "progress": 0, "stage": None, "message": None}

    await websocket.send_text(json.dumps(state))
    if state.get("state") in terminal:
        await websocket.close(code=1000)
        return

    pubsub = get_redis().pubsub()
    channel = job_channel(str(job_id))
    pubsub.subscribe(channel)
    last_auth_check = time.time()

    try:
        while True:
            now_time = time.time()
            if now_time - last_auth_check >= 30:
                last_auth_check = now_time
                with SessionLocal() as check_db:
                    u = check_db.get(User, user_id)
                    if not u or not u.active or not u.credentials_ready or u.password_reset_required:
                        await websocket.close(code=4403)
                        break
                    j = check_db.get(ExtractionJob, str(job_id))
                    p_id = None
                    if j:
                        d = check_db.get(StoredDocument, j.document_id)
                        if d:
                            p_id = d.patient_id
                    else:
                        sj = check_db.get(SummaryJob, str(job_id))
                        if sj:
                            j = sj
                            p_id = sj.patient_id
                    c_caps = getattr(u, "capabilities", []) or []
                    if not j or not p_id or "clinical:read" not in c_caps or not has_access(check_db, u, p_id):
                        await websocket.close(code=4403)
                        break

            msg = await asyncio.to_thread(pubsub.get_message, ignore_subscribe_messages=True, timeout=1.0)
            if msg is None:
                continue
            if msg.get("type") == "message":
                data = msg.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                await websocket.send_text(data)
                try:
                    event = json.loads(data)
                    if event.get("state") in {"completed", "failed", "cancelled"}:
                        await websocket.close(code=1000)
                        break
                except Exception:
                    pass
    except WebSocketDisconnect:
        pass
    finally:
        try:
            pubsub.unsubscribe(channel)
        except Exception:
            pass
        try:
            pubsub.close()
        except Exception:
            pass
