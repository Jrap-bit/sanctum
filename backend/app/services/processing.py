from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from ..adapters.crypto import decrypt
from ..core.cache import publish_progress
from ..db.models import DocumentImport
from ..db.models import ExtractedPage
from ..db.models import ExtractionJob
from ..db.models import StoredDocument
from ..db.models import now
from .audit import record_audit
from .authorization import has_access
from .authorization import require
from .authorization import scoped_patient
from .documents import output as document_output
from .raw_text import delete_raw
from .raw_text import get_raw
from . import review as review_service


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


def start(db, user, request, patient_id, document_id):
    return enqueue(db, request, user, patient_id, document_id)


def retry(db, user, request, patient_id, document_id):
    return enqueue(db, request, user, patient_id, document_id, retry=True)


def cancel(db, user, request, patient_id, document_id):
    require(user, "documents:write")
    doc = find_document(db, user, patient_id, document_id)
    if doc.withdrawn_at is not None:
        raise HTTPException(409, "Withdrawn documents cannot be processed.")
    job = db.scalar(
        select(ExtractionJob)
        .where(ExtractionJob.document_id == doc.id)
        .with_for_update()
    )
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


def withdraw(db, user, request, patient_id, document_id):
    require(user, "documents:write")
    doc = find_document(db, user, patient_id, document_id, write=True)
    if db.get(DocumentImport, doc.id):
        raise HTTPException(409, "This document is already imported. Amend its historical notes to correct them.")
    if doc.withdrawn_at is not None:
        raise HTTPException(409, "This document is already withdrawn.")
    doc.withdrawn_at = now()
    job = db.scalar(
        select(ExtractionJob)
        .where(ExtractionJob.document_id == doc.id)
        .with_for_update()
    )
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


def pages(db, user, request, patient_id, document_id):
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
        items.append(review_service.page_output(doc, page_number, row, raw))

    imported = db.get(DocumentImport, doc.id)
    imported_result = (
        decrypt(imported.payload, f"document-import:{doc.patient_id}:{doc.id}")["result"]
        if imported
        else None
    )
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


def jobs(db, user, request):
    require(user, "operations:manage")
    rows = db.execute(
        select(ExtractionJob, StoredDocument.page_count)
        .join(StoredDocument, StoredDocument.id == ExtractionJob.document_id)
        .order_by(ExtractionJob.created_at.desc())
        .limit(100)
    ).all()
    from ..db.models import SummaryJob
    from .summaries import job_output as summary_job_output

    summary_jobs = db.scalars(
        select(SummaryJob).order_by(SummaryJob.created_at.desc()).limit(100)
    ).all()
    entries = [(j.created_at, {**job_output(j, count), "kind": "extraction"}) for j, count in rows]
    entries += [(j.created_at, summary_job_output(j)) for j in summary_jobs]
    entries.sort(key=lambda item: item[0], reverse=True)
    result = {"items": [item[1] for item in entries[:100]]}
    record_audit(db, request, user, "processing.jobs_read", None)
    db.commit()
    return result
