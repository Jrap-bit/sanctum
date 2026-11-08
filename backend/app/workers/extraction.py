"""Run with python -m app.worker; PostgreSQL owns the durable job queue."""
import argparse
from datetime import timedelta
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from uuid import uuid4

from sqlalchemy import or_, select

from ..core.cache import publish_progress
from ..core.database import SessionLocal
from ..db.models import AuditEvent, ExtractionJob, Patient, StoredDocument, User, now
from ..services.authorization import has_access
from ..services.documents import original_bytes
from ..services.raw_text import put_raw


LEASE_SECONDS = 180


ERRORS = {
    "ocr_unavailable": "OCR is unavailable. Install Tesseract or check TESSERACT_COMMAND, then retry.",
    "ocr_failed": "OCR could not read this page. Check the installed language data and source file, then retry.",
    "page_timeout": "A page exceeded the processing time limit. Try a smaller or clearer source document.",
    "page_text_limit": "A page contains too much text to process safely.",
    "page_size": "A page is too large or has invalid dimensions.",
    "extraction_failed": "Text extraction failed. Check the original file and retry.",
}


def permitted(db, doc, job):
    user = db.get(User, job.requested_by)
    patient = db.get(Patient, doc.patient_id)
    return bool(
        user
        and user.active
        and user.credentials_ready
        and not user.password_reset_required
        and {"documents:write", "clinical:read"} <= set(user.capabilities)
        and patient
        and patient.status == "active"
        and has_access(db, user, patient.id, write=True)
    )


def audit(db, job, action, outcome="success"):
    db.add(
        AuditEvent(
            actor_id=job.requested_by,
            target_id=job.document_id,
            action=action,
            outcome=outcome,
            request_id=job.run_id or str(uuid4()),
        )
    )


def claim(factory):
    with factory() as db:
        job = db.scalar(
            select(ExtractionJob)
            .where(
                or_(
                    ExtractionJob.state == "queued",
                    (ExtractionJob.state == "running") & (ExtractionJob.lease_until < now()),
                )
            )
            .order_by(ExtractionJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        doc = db.get(StoredDocument, job.document_id)
        if not permitted(db, doc, job):
            job.state = "cancelled"
            job.message = "Processing stopped because patient access or account status changed."
            job.run_id = None
            job.lease_until = None
            job.completed_pages = 0
            audit(db, job, "document.extraction_cancelled")
            publish_progress(job.id, state="cancelled", message=job.message)
            db.commit()
            return ()
        if job.attempts >= 3:
            job.state = "failed"
            job.message = "Processing was interrupted repeatedly. Check the worker and retry."
            job.lease_until = None
            job.run_id = None
            audit(db, job, "document.extraction_failed", "failure")
            publish_progress(job.id, state="failed", message=job.message)
            db.commit()
            return ()
        job.state = "running"
        job.attempts += 1
        job.run_id = str(uuid4())
        job.completed_pages = 0
        job.lease_until = now() + timedelta(seconds=LEASE_SECONDS)
        job.updated_at = now()
        job.message = None
        ticket = (job.id, job.run_id, doc.id, doc.media_type, doc.page_count)
        audit(db, job, "document.extraction_started")
        db.commit()
        return ticket


def extract_one(raw, mime, page):
    command = [sys.executable, "-m", "app.adapters.extract_page", mime, str(page)]
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=Path(__file__).resolve().parents[2],
        start_new_session=True,
    )
    try:
        stdout, _ = process.communicate(raw, timeout=90)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise ValueError("page_timeout") from None
    try:
        result = json.loads(stdout)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("extraction_failed") from None
    if process.returncode or "error" in result:
        raise ValueError(result.get("error", "extraction_failed"))
    return result


def current_job(db, job_id, run_id):
    job = db.scalar(
        select(ExtractionJob)
        .where(ExtractionJob.id == job_id)
        .with_for_update()
    )
    if job is None or job.state != "running" or job.run_id != run_id:
        return None
    return job


def run_once(factory=SessionLocal, extractor=extract_one):
    ticket = claim(factory)
    if ticket is None:
        return False
    if not ticket:
        return True
    job_id, run_id, doc_id, mime, count = ticket
    publish_progress(job_id, state="running", progress=0)
    try:
        with factory() as db:
            raw = original_bytes(db.get(StoredDocument, doc_id))
        for number in range(1, count + 1):
            with factory() as db:
                if current_job(db, job_id, run_id) is None:
                    return True
            result = extractor(raw, mime, number)
            with factory() as db:
                job = current_job(db, job_id, run_id)
                if job is None:
                    return True
                doc = db.get(StoredDocument, doc_id)
                if not permitted(db, doc, job):
                    job.state = "cancelled"
                    job.message = "Processing stopped because patient access or account status changed."
                    job.run_id = None
                    job.lease_until = None
                    job.completed_pages = 0
                    audit(db, job, "document.extraction_cancelled")
                    publish_progress(job.id, state="cancelled", message=job.message)
                    db.commit()
                    return True
                text = result["rawText"]
                if not isinstance(text, str) or len(text) > 100_000 or result["method"] not in {"embedded_text", "ocr"}:
                    raise ValueError("extraction_failed")
                payload = {
                    "rawText": text,
                    "method": result["method"],
                    "unreadable": result.get("unreadable", not bool(text.strip())),
                    "regions": result.get("regions", []),
                }
                put_raw(doc, number, payload)
                job.completed_pages = number
                job.updated_at = now()
                job.lease_until = now() + timedelta(seconds=LEASE_SECONDS)
                progress_pct = int(number * 100 / count)
                publish_progress(job_id, state="running", progress=progress_pct, stage=f"Page {number} of {count}")
                if number == count:
                    job.state = "completed"
                    job.lease_until = None
                    audit(db, job, "document.extraction_completed")
                    publish_progress(job_id, state="completed", progress=100, message=job.message)
                db.commit()
    except Exception as exc:
        with factory() as db:
            job = current_job(db, job_id, run_id)
            if job:
                job.state = "failed"
                job.message = ERRORS.get(str(exc), ERRORS["extraction_failed"])
                job.lease_until = None
                job.updated_at = now()
                job.completed_pages = 0
                audit(db, job, "document.extraction_failed", "failure")
                publish_progress(job.id, state="failed", message=job.message)
                db.commit()
    return True


def main():
    parser = argparse.ArgumentParser(description="Process queued Sanctum document extraction jobs locally")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.once:
        run_once()
        return
    print("Document worker started. Press Ctrl+C to stop.", flush=True)
    try:
        while True:
            try:
                if not run_once():
                    time.sleep(2)
            except Exception:
                print("Worker could not access its queue. Retrying in 5 seconds.", flush=True)
                time.sleep(5)
    except KeyboardInterrupt:
        print("Worker stopped. Interrupted work will be recovered after its lease expires.", flush=True)


if __name__ == "__main__":
    main()
