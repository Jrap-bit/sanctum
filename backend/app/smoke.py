"""Real running deployment verification through the public API over HTTP."""
from io import BytesIO
import secrets
import time
from uuid import uuid4

import httpx
from PIL import Image
from PIL import ImageDraw
from sqlalchemy import select

from .core.config import get_settings
from .core.database import SessionLocal
from .db.models import User
from .manage import create_user
from .services.session_store import delete_user_sessions

VALID_OUTCOMES = {"matched", "not_matched", "not_evaluable"}
FIXED_SENTENCE = "Synthetic smoke test session note sentence."
DOCUMENT_SENTENCE = "Synthetic smoke test document page."


def create_document_image() -> bytes:
    img = Image.new("RGB", (600, 100), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 30), DOCUMENT_SENTENCE, fill="black")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def run(base_url="http://127.0.0.1:8000", out=print, poll_interval=1.0, transport=None, client=None) -> bool:
    settings = get_settings()
    origin = settings.allowed_origin
    hex_id = secrets.token_hex(4)
    username = f"smoke_{hex_id}"
    user_name = f"Smoke Tester {hex_id}"
    patient_name = f"Smoke Test {hex_id}"
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    password = "".join(secrets.choice(alphabet) for _ in range(32))

    user_id = None
    try:
        with SessionLocal() as db:
            user = create_user(db, username, user_name, "clinician", password)
            user_id = user.id
    except Exception:
        out("FAIL  setup: database unavailable")
        out("SANCTUM SMOKE TEST FAIL")
        return False

    def make_client():
        if client is not None:
            return client
        client_kwargs = {
            "base_url": base_url,
            "headers": {"Origin": origin},
            "timeout": 30.0,
        }
        if transport is not None:
            client_kwargs["transport"] = transport
        return httpx.Client(**client_kwargs)

    current_check = ""

    def fail(check_name: str, reason: str) -> bool:
        out(f"FAIL  {check_name}: {reason}")
        out("SANCTUM SMOKE TEST FAIL")
        return False

    try:
        http = make_client()
        with http:
            # 1. health
            current_check = "health"
            try:
                resp = http.get("/api/v1/health")
                if resp.status_code != 200:
                    return fail(current_check, f"status {resp.status_code}")
            except (httpx.RequestError, httpx.HTTPError):
                return fail(current_check, "connection error")
            out(f"PASS  {current_check}")

            # 2. login
            current_check = "login"
            try:
                resp = http.post(
                    "/api/v1/auth/login",
                    json={"username": username, "password": password},
                )
                if resp.status_code != 200:
                    return fail(current_check, f"status {resp.status_code}")
            except (httpx.RequestError, httpx.HTTPError):
                return fail(current_check, "connection error")
            out(f"PASS  {current_check}")

            # 3. scoped write
            current_check = "scoped write"
            try:
                resp = http.post("/api/v1/patients", json={"displayName": patient_name})
                if resp.status_code != 201:
                    return fail(current_check, f"patient create status {resp.status_code}")
                patient_id = resp.json().get("id")
                if not patient_id:
                    return fail(current_check, "missing patient id")

                resp = http.post(f"/api/v1/patients/{patient_id}/sessions", json={})
                if resp.status_code != 201:
                    return fail(current_check, f"session create status {resp.status_code}")
                session_id = resp.json().get("id")
                session_version = resp.json().get("version", 1)
                if not session_id:
                    return fail(current_check, "missing session id")

                resp = http.patch(
                    f"/api/v1/patients/{patient_id}/sessions/{session_id}",
                    json={
                        "expectedVersion": session_version,
                        "text": FIXED_SENTENCE,
                        "concerns": [],
                        "observations": [],
                        "interventions": [],
                        "medicationReported": [],
                    },
                )
                if resp.status_code != 200:
                    return fail(current_check, f"session save status {resp.status_code}")
                session_version = resp.json().get("version", session_version + 1)

                resp = http.post(
                    f"/api/v1/patients/{patient_id}/sessions/{session_id}/finalize",
                    json={"expectedVersion": session_version},
                )
                if resp.status_code != 200:
                    return fail(current_check, f"session finalize status {resp.status_code}")
                note_version = resp.json().get("version", session_version + 1)
            except (httpx.RequestError, httpx.HTTPError):
                return fail(current_check, "connection error")
            out(f"PASS  {current_check}")

            # 4. scoped read
            current_check = "scoped read"
            try:
                resp = http.get(f"/api/v1/patients/{patient_id}/sessions/{session_id}")
                if resp.status_code != 200:
                    return fail(current_check, f"status {resp.status_code}")
                if resp.json().get("text") != FIXED_SENTENCE:
                    return fail(current_check, "text mismatch")

                fresh_kwargs = {
                    "base_url": base_url,
                    "headers": {"Origin": origin},
                    "timeout": 30.0,
                }
                if transport is not None:
                    fresh_kwargs["transport"] = transport
                elif client is not None and hasattr(client, "_transport"):
                    fresh_kwargs["transport"] = client._transport
                with httpx.Client(**fresh_kwargs) as fresh_client:
                    resp_fresh = fresh_client.get(f"/api/v1/patients/{patient_id}/sessions/{session_id}")
                    if resp_fresh.status_code != 401:
                        return fail(current_check, f"expected 401, got {resp_fresh.status_code}")
            except (httpx.RequestError, httpx.HTTPError):
                return fail(current_check, "connection error")
            out(f"PASS  {current_check}")

            # 5. document upload
            current_check = "document upload"
            try:
                png_bytes = create_document_image()
                resp = http.post(
                    f"/api/v1/patients/{patient_id}/documents",
                    files={"file": ("page.png", png_bytes, "image/png")},
                )
                if resp.status_code != 201:
                    return fail(current_check, f"status {resp.status_code}")
                document_id = resp.json().get("id")
                if not document_id:
                    return fail(current_check, "missing document id")
            except (httpx.RequestError, httpx.HTTPError):
                return fail(current_check, "connection error")
            out(f"PASS  {current_check}")

            # 6. ocr
            current_check = "ocr"
            try:
                resp = http.post(f"/api/v1/patients/{patient_id}/documents/{document_id}/process")
                if resp.status_code != 202:
                    return fail(current_check, f"process status {resp.status_code}")

                start_time = time.time()
                ocr_completed = False
                while time.time() - start_time < 120:
                    resp = http.get(f"/api/v1/patients/{patient_id}/documents")
                    if resp.status_code != 200:
                        return fail(current_check, f"list status {resp.status_code}")
                    items = resp.json().get("items", [])
                    doc = next((d for d in items if d.get("id") == document_id), None)
                    if doc is None:
                        return fail(current_check, "document missing in listing")
                    state = doc.get("jobState")
                    if state == "completed":
                        ocr_completed = True
                        break
                    if state in ("failed", "cancelled"):
                        return fail(current_check, f"job ended with state {state}")
                    time.sleep(poll_interval)
                if not ocr_completed:
                    return fail(current_check, "timed out waiting for extraction")

                resp = http.get(f"/api/v1/patients/{patient_id}/documents/{document_id}/pages")
                if resp.status_code != 200:
                    return fail(current_check, f"pages status {resp.status_code}")
                pages = resp.json().get("pages", [])
                if not pages:
                    return fail(current_check, "no pages returned")
                page1 = pages[0]
                raw_text = page1.get("rawText", "")
                if not raw_text or not raw_text.strip():
                    return fail(current_check, "rawText is empty")
                page1_version = page1.get("version", 1)
            except (httpx.RequestError, httpx.HTTPError):
                return fail(current_check, "connection error")
            out(f"PASS  {current_check}")

            # 7. import review
            current_check = "import review"
            try:
                resp = http.patch(
                    f"/api/v1/patients/{patient_id}/documents/{document_id}/pages/1",
                    json={
                        "expectedVersion": page1_version,
                        "correctedText": raw_text,
                        "included": True,
                        "unreadable": False,
                    },
                )
                if resp.status_code != 200:
                    return fail(current_check, f"patch page status {resp.status_code}")
                doc_version = resp.json().get("documentVersion", 2)

                resp = http.post(
                    f"/api/v1/patients/{patient_id}/documents/{document_id}/confirm",
                    json={
                        "expectedVersion": doc_version,
                        "groups": [
                            {
                                "pageNumbers": [1],
                                "dateStatus": "unknown",
                                "eventDate": None,
                            }
                        ],
                    },
                )
                if resp.status_code != 200:
                    return fail(current_check, f"confirm status {resp.status_code}")
            except (httpx.RequestError, httpx.HTTPError):
                return fail(current_check, "connection error")
            out(f"PASS  {current_check}")

            # 8. local generation
            current_check = "local generation"
            try:
                resp = http.post(
                    f"/api/v1/patients/{patient_id}/summaries",
                    json={
                        "kind": "single_session",
                        "sourceVersions": [
                            {
                                "id": session_id,
                                "version": note_version,
                                "type": "session",
                            }
                        ],
                        "requestKey": str(uuid4()),
                    },
                )
                if resp.status_code != 202:
                    return fail(current_check, f"summary request status {resp.status_code}")
                job_id = resp.json().get("id")
                if not job_id:
                    return fail(current_check, "missing summary job id")

                start_time = time.time()
                result_id = None
                while time.time() - start_time < 300:
                    resp = http.get(f"/api/v1/jobs/{job_id}")
                    if resp.status_code != 200:
                        return fail(current_check, f"job status {resp.status_code}")
                    job_info = resp.json()
                    job_state = job_info.get("state")
                    if job_state == "completed":
                        result_id = job_info.get("resultId")
                        break
                    if job_state in ("failed", "cancelled"):
                        return fail(current_check, f"generation {job_state}")
                    time.sleep(poll_interval)
                if not result_id:
                    return fail(current_check, "missing resultId after generation")

                resp = http.get(f"/api/v1/patients/{patient_id}/summaries/{result_id}")
                if resp.status_code != 200:
                    return fail(current_check, f"summary get status {resp.status_code}")
                summary_data = resp.json()
                summary_text = summary_data.get("text", "")
                if not summary_text or not summary_text.strip():
                    return fail(current_check, "summary text is empty")
                evidence = summary_data.get("evidence", [])
                if len(evidence) < 1:
                    return fail(current_check, "no evidence entry in summary")
                summary_id = result_id
                summary_version = summary_data.get("version", 1)
            except (httpx.RequestError, httpx.HTTPError):
                return fail(current_check, "connection error")
            out(f"PASS  {current_check}")

            # 9. summary review
            current_check = "summary review"
            try:
                resp = http.post(
                    f"/api/v1/patients/{patient_id}/summaries/{summary_id}/review",
                    json={"expectedVersion": summary_version, "decision": "accept"},
                )
                if resp.status_code != 200:
                    return fail(current_check, f"review status {resp.status_code}")
                reviewed_summary = resp.json()
                if reviewed_summary.get("reviewState") != "accepted":
                    return fail(current_check, "summary was not accepted")
                facts = reviewed_summary.get("facts", [])
                for fact in facts:
                    if fact.get("state") != "pending":
                        return fail(current_check, "pending fact did not stay pending")
                summary_version = reviewed_summary.get("version", summary_version + 1)
            except (httpx.RequestError, httpx.HTTPError):
                return fail(current_check, "connection error")
            out(f"PASS  {current_check}")

            # 10. rule evaluation
            current_check = "rule evaluation"
            try:
                resp = http.post(f"/api/v1/patients/{patient_id}/indicators/evaluate")
                if resp.status_code != 200:
                    return fail(current_check, f"evaluate status {resp.status_code}")
                items = resp.json().get("items", [])
                for item in items:
                    outcome = item.get("outcome")
                    if outcome not in VALID_OUTCOMES:
                        return fail(current_check, f"invalid outcome: {outcome}")
                    if "ruleVersion" not in item or item["ruleVersion"] is None:
                        return fail(current_check, "missing ruleVersion")
            except (httpx.RequestError, httpx.HTTPError):
                return fail(current_check, "connection error")
            out(f"PASS  {current_check}")

            # 11. report export
            current_check = "report export"
            try:
                resp = http.post(
                    f"/api/v1/patients/{patient_id}/reports/preview",
                    json={
                        "sourceVersions": [
                            {
                                "id": session_id,
                                "version": note_version,
                                "type": "session",
                            }
                        ]
                    },
                )
                if resp.status_code != 200:
                    return fail(current_check, f"preview status {resp.status_code}")
                manifest = resp.json()
                report_id = manifest.get("id")
                if not report_id:
                    return fail(current_check, "missing report id")
                included = manifest.get("included", [])
                if not any(item.get("id") == summary_id for item in included):
                    return fail(current_check, "accepted summary not in included")

                resp = http.get(f"/api/v1/patients/{patient_id}/reports/{report_id}/export")
                if resp.status_code != 200:
                    return fail(current_check, f"export status {resp.status_code}")
                if not resp.content.startswith(b"%PDF-"):
                    return fail(current_check, "export content is not PDF")
            except (httpx.RequestError, httpx.HTTPError):
                return fail(current_check, "connection error")
            out(f"PASS  {current_check}")

    except Exception:
        return fail(current_check or "smoke test", "unexpected error")
    finally:
        if user_id is not None:
            try:
                with SessionLocal() as db:
                    u = db.scalar(select(User).where(User.id == user_id).with_for_update())
                    if u is not None:
                        u.active = False
                        db.commit()
            except Exception:
                pass
            try:
                delete_user_sessions(user_id)
            except Exception:
                pass

    out("SANCTUM SMOKE TEST PASS")
    return True
