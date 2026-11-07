from .patients import has_access
"""Durable extraction requests and protected access to draft page text."""
from datetime import datetime
from uuid import UUID, uuid4
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import delete, select
from .auth import CurrentUser, Db
from .crypto import decrypt
from .models import ExtractionJob, ExtractedPage, StoredDocument, DocumentImport, now
from .patients import require, scoped_patient, record_audit

router = APIRouter(tags=['Document processing'])
PREFIX = '/api/v1/patients/{patient_id}/documents/{document_id}'


def find_document(db, user, patient_id, document_id, *, write=False):
    if write: require(user, 'documents:write')
    patient = scoped_patient(db, user, patient_id, clinical=True, lock=write)
    if write and patient.status != 'active':
        raise HTTPException(409, 'Reactivate the patient before processing documents.')
    row = db.scalar(select(StoredDocument).where(StoredDocument.id == str(document_id), StoredDocument.patient_id == patient.id))
    if row is None: raise HTTPException(404, 'Document unavailable.')
    return row


def job_output(job, pages):
    return {'id': job.id, 'state': job.state, 'progress': int(job.completed_pages * 100 / pages),
            'resultId': job.document_id, 'message': job.message, 'createdAt': job.created_at}


def enqueue(db, request, user, patient_id, document_id, retry=False):
    doc = find_document(db, user, patient_id, document_id, write=True)
    job = db.scalar(select(ExtractionJob).where(ExtractionJob.document_id == doc.id).with_for_update())
    if job is not None:
        if job.state not in {'failed', 'cancelled'}:
            raise HTTPException(409, 'This document is already queued, processing or extracted.')
        db.execute(delete(ExtractedPage).where(ExtractedPage.document_id == doc.id))
        job.state = 'queued'; job.completed_pages = 0; job.run_id = None
        job.lease_until = None; job.message = None; job.attempts = 0
        job.requested_by = user.id; job.updated_at = now()
    else:
        if retry: raise HTTPException(409, 'Start extraction before retrying it.')
        job = ExtractionJob(id=str(uuid4()), document_id=doc.id, requested_by=user.id, state='queued', completed_pages=0)
        db.add(job)
    record_audit(db, request, user, 'document.extraction_requested', doc.id)
    db.flush(); result = job_output(job, doc.page_count); db.commit()
    return result


@router.post(PREFIX + '/process', status_code=202)
def start(patient_id: UUID, document_id: UUID, user: CurrentUser, db: Db, request: Request):
    return enqueue(db, request, user, patient_id, document_id)


@router.post(PREFIX + '/retry', status_code=202)
def retry(patient_id: UUID, document_id: UUID, user: CurrentUser, db: Db, request: Request):
    return enqueue(db, request, user, patient_id, document_id, retry=True)


@router.post(PREFIX + '/cancel')
def cancel(patient_id: UUID, document_id: UUID, user: CurrentUser, db: Db, request: Request):
    # Cancellation also works after the patient is archived.
    require(user, 'documents:write')
    doc = find_document(db, user, patient_id, document_id)
    job = db.scalar(select(ExtractionJob).where(ExtractionJob.document_id == doc.id).with_for_update())
    if job is None or job.state not in {'queued', 'running'}:
        raise HTTPException(409, 'There is no active extraction to cancel.')
    job.state = 'cancelled'; job.run_id = None; job.lease_until = None; job.updated_at = now()
    job.completed_pages = 0
    db.execute(delete(ExtractedPage).where(ExtractedPage.document_id == doc.id))
    record_audit(db, request, user, 'document.extraction_cancelled', doc.id)
    result = job_output(job, doc.page_count); db.commit()
    return result


@router.get(PREFIX + '/pages')
def pages(patient_id: UUID, document_id: UUID, user: CurrentUser, db: Db, request: Request):
    doc = find_document(db, user, patient_id, document_id)
    job = db.scalar(select(ExtractionJob).where(ExtractionJob.document_id == doc.id))
    if job is None or job.state != 'completed':
        raise HTTPException(409, 'Text extraction has not completed. Check the document processing status.')
    rows = db.scalars(select(ExtractedPage).where(ExtractedPage.document_id == doc.id).order_by(ExtractedPage.page_number)).all()
    from .review import page_output
    items = [page_output(doc, row) for row in rows]
    imported = db.get(DocumentImport, doc.id)
    imported_result = decrypt(imported.payload, f'document-import:{doc.patient_id}:{doc.id}')['result'] if imported else None
    filename = decrypt(doc.metadata_payload, f'document-meta:{doc.patient_id}:{doc.id}')['filename']
    record_audit(db, request, user, 'document.pages_read', doc.id)
    db.commit()
    return {'filename': filename, 'version': doc.review_version, 'pages': items, 'imported': imported_result,
            'allowedActions': ['review'] if not imported and has_access(db,user,doc.patient_id,write=True) and 'documents:write' in user.capabilities else []}


@router.get('/api/v1/admin/operations/jobs')
def jobs(user: CurrentUser, db: Db, request: Request):
    require(user, 'operations:manage')
    rows = db.execute(select(ExtractionJob, StoredDocument.page_count).join(StoredDocument, StoredDocument.id == ExtractionJob.document_id)
                      .order_by(ExtractionJob.created_at.desc()).limit(100)).all()
    from .models import SummaryJob
    from .summaries import job_output as summary_job_output
    summary_jobs = db.scalars(select(SummaryJob).order_by(SummaryJob.created_at.desc()).limit(100)).all()
    entries = [(j.created_at, {**job_output(j, count), 'kind': 'extraction'}) for j, count in rows]
    entries += [(j.created_at, summary_job_output(j)) for j in summary_jobs]
    entries.sort(key=lambda item: item[0], reverse=True)
    result = {'items': [item[1] for item in entries[:100]]}
    record_audit(db, request, user, 'processing.jobs_read', None); db.commit()
    return result
