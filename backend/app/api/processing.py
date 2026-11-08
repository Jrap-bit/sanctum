"""Durable extraction requests and protected access to draft page text."""
from uuid import UUID
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from ..adapters.crypto import decrypt
from ..core.cache import publish_progress
from ..db.models import DocumentImport, ExtractedPage, ExtractionJob, StoredDocument, now
from ..services.audit import record_audit
from ..services.authorization import has_access, require
from ..services.documents import output as document_output
from ..services.processing import enqueue, find_document, job_output
from ..services.raw_text import delete_raw, get_raw
from ..services.review import page_output
from .deps import CurrentUser, Db


router = APIRouter(tags=["Document processing"])


PREFIX = "/api/v1/patients/{patient_id}/documents/{document_id}"


@router.post(PREFIX + "/process", status_code=202)
def start(patient_id: UUID, document_id: UUID, user: CurrentUser, db: Db, request: Request):
    return enqueue(db, request, user, patient_id, document_id)


@router.post(PREFIX + "/retry", status_code=202)
def retry(patient_id: UUID, document_id: UUID, user: CurrentUser, db: Db, request: Request):
    return enqueue(db, request, user, patient_id, document_id, retry=True)


@router.post(PREFIX + "/cancel")
def cancel(patient_id: UUID, document_id: UUID, user: CurrentUser, db: Db, request: Request):
    require(user, "documents:write")
    doc = find_document(db, user, patient_id, document_id)
    if doc.withdrawn_at is not None:
        raise HTTPException(409, "Withdrawn documents cannot be processed.")
    job = db.scalar(select(ExtractionJob).where(ExtractionJob.document_id == doc.id).with_for_update())
    if job is None or job.state not in {"queued", "running"}:
        raise HTTPException(409, "There is no active extraction to cancel.")
    job.state = "cancelled"
    job.run_id = None
    job.lease_until = None
    job.updated_at = now()
    job.completed_pages = 0
    record_audit(db, request, user, "document.extraction_cancelled", doc.id)
    publish_progress(job.id, state="cancelled", message=job.message)
    result = job_output(job, doc.page_count)
    db.commit()
    return result


@router.post(PREFIX + "/withdraw")
def withdraw(patient_id: UUID, document_id: UUID, user: CurrentUser, db: Db, request: Request):
    require(user, "documents:write")
    doc = find_document(db, user, patient_id, document_id, write=True)
    if db.get(DocumentImport, doc.id):
        raise HTTPException(409, "This document is already imported. Amend its historical notes to correct them.")
    if doc.withdrawn_at is not None:
        raise HTTPException(409, "This document is already withdrawn.")
    doc.withdrawn_at = now()
    job = db.scalar(select(ExtractionJob).where(ExtractionJob.document_id == doc.id).with_for_update())
    if job and job.state in {"queued", "running"}:
        job.state = "cancelled"
        job.run_id = None
        job.lease_until = None
        job.completed_pages = 0
        job.message = "Document withdrawn."
        job.updated_at = now()
        publish_progress(job.id, state="cancelled", message=job.message)
    delete_raw(doc)
    record_audit(db, request, user, "document.withdrawn", doc.id)
    db.flush()
    result = document_output(db, doc, user=user)
    db.commit()
    return result


@router.get(PREFIX + "/pages")
def pages(patient_id: UUID, document_id: UUID, user: CurrentUser, db: Db, request: Request):
    doc = find_document(db, user, patient_id, document_id)
    job = db.scalar(select(ExtractionJob).where(ExtractionJob.document_id == doc.id))
    if job is None or job.state != "completed":
        raise HTTPException(409, "Text extraction has not completed. Check the document processing status.")

    rows = db.scalars(
        select(ExtractedPage)
        .where(ExtractedPage.document_id == doc.id)
    ).all()
    rows_by_page = {r.page_number: r for r in rows}

    has_perm = ("documents:write" in (user.capabilities or [])) and has_access(db, user, doc.patient_id, write=True)

    items = []
    for page_number in range(1, doc.page_count + 1):
        row = rows_by_page.get(page_number)
        raw = get_raw(doc, page_number)
        if row is None and raw is None:
            if has_perm:
                job.state = "queued"
                job.attempts = 0
                job.run_id = None
                job.lease_until = None
                job.completed_pages = 0
                job.updated_at = now()
                record_audit(db, request, user, "document.extraction_requeued", doc.id)
                db.commit()
                raise HTTPException(409, "The draft text has expired and is being extracted again. Try again shortly.")
            else:
                raise HTTPException(409, "The draft text has expired. Ask someone with document access to extract it again.")
        items.append(page_output(doc, page_number, row, raw))

    imported = db.get(DocumentImport, doc.id)
    imported_result = decrypt(imported.payload, f"document-import:{doc.patient_id}:{doc.id}")["result"] if imported else None
    filename = decrypt(doc.metadata_payload, f"document-meta:{doc.patient_id}:{doc.id}")["filename"]
    record_audit(db, request, user, "document.pages_read", doc.id)
    db.commit()
    return {
        "filename": filename,
        "version": doc.review_version,
        "pages": items,
        "imported": imported_result,
        "allowedActions": (
            ["review"]
            if not imported
            and has_access(db, user, doc.patient_id, write=True)
            and "documents:write" in user.capabilities
            and doc.withdrawn_at is None
            else []
        ),
    }


@router.get("/api/v1/admin/operations/jobs")
def jobs(user: CurrentUser, db: Db, request: Request):
    require(user, "operations:manage")
    rows = db.execute(
        select(ExtractionJob, StoredDocument.page_count)
        .join(StoredDocument, StoredDocument.id == ExtractionJob.document_id)
        .order_by(ExtractionJob.created_at.desc())
        .limit(100)
    ).all()
    from ..db.models import SummaryJob
    from ..services.summaries import job_output as summary_job_output

    summary_jobs = db.scalars(select(SummaryJob).order_by(SummaryJob.created_at.desc()).limit(100)).all()
    entries = [(j.created_at, {**job_output(j, count), "kind": "extraction"}) for j, count in rows]
    entries += [(j.created_at, summary_job_output(j)) for j in summary_jobs]
    entries.sort(key=lambda item: item[0], reverse=True)
    result = {"items": [item[1] for item in entries[:100]]}
    record_audit(db, request, user, "processing.jobs_read", None)
    db.commit()
    return result
