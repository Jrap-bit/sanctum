from fastapi import HTTPException
from sqlalchemy import select
from uuid import uuid4

from ..db.models import ExtractionJob, StoredDocument, now
from .audit import record_audit
from .authorization import require, scoped_patient


def find_document(db, user, patient_id, document_id, *, write=False):
    if write:
        require(user, "documents:write")
    patient = scoped_patient(db, user, patient_id, clinical=True, lock=write)
    if write and patient.status != "active":
        raise HTTPException(409, "Reactivate the patient before processing documents.")
    row = db.scalar(
        select(StoredDocument).where(
            StoredDocument.id == str(document_id),
            StoredDocument.patient_id == patient.id,
        )
    )
    if row is None:
        raise HTTPException(404, "Document unavailable.")
    return row


def job_output(job, pages):
    return {
        "id": job.id,
        "state": job.state,
        "progress": int(job.completed_pages * 100 / pages) if pages else 0,
        "resultId": job.document_id,
        "message": job.message,
        "createdAt": job.created_at,
    }


def enqueue(db, request, user, patient_id, document_id, retry=False):
    doc = find_document(db, user, patient_id, document_id, write=True)
    if doc.withdrawn_at is not None:
        raise HTTPException(409, "Withdrawn documents cannot be processed.")
    job = db.scalar(
        select(ExtractionJob).where(ExtractionJob.document_id == doc.id).with_for_update()
    )
    if job is not None:
        if job.state not in {"failed", "cancelled"}:
            raise HTTPException(409, "This document is already queued, processing or extracted.")
        job.state = "queued"
        job.completed_pages = 0
        job.run_id = None
        job.lease_until = None
        job.message = None
        job.attempts = 0
        job.requested_by = user.id
        job.updated_at = now()
    else:
        if retry:
            raise HTTPException(409, "Start extraction before retrying it.")
        job = ExtractionJob(
            id=str(uuid4()),
            document_id=doc.id,
            requested_by=user.id,
            state="queued",
            completed_pages=0,
        )
        db.add(job)
    record_audit(db, request, user, "document.extraction_requested", doc.id)
    db.flush()
    result = job_output(job, doc.page_count)
    db.commit()
    return result
