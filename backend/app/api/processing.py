"""Durable extraction requests and protected access to draft page text."""
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from sqlalchemy import delete
from sqlalchemy import select
from uuid import UUID

from ..adapters.crypto import decrypt
from ..db.models import DocumentImport
from ..db.models import ExtractedPage
from ..db.models import ExtractionJob
from ..db.models import StoredDocument
from ..db.models import now
from ..services.audit import record_audit
from ..services.authorization import has_access
from ..services.authorization import require
from ..services.processing import enqueue
from ..services.processing import find_document
from ..services.processing import job_output
from .deps import CurrentUser
from .deps import Db


router = APIRouter(tags=['Document processing'])


PREFIX = '/api/v1/patients/{patient_id}/documents/{document_id}'


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
    from ..services.review import page_output
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
    from ..db.models import SummaryJob
    from ..services.summaries import job_output as summary_job_output
    summary_jobs = db.scalars(select(SummaryJob).order_by(SummaryJob.created_at.desc()).limit(100)).all()
    entries = [(j.created_at, {**job_output(j, count), 'kind': 'extraction'}) for j, count in rows]
    entries += [(j.created_at, summary_job_output(j)) for j in summary_jobs]
    entries.sort(key=lambda item: item[0], reverse=True)
    result = {'items': [item[1] for item in entries[:100]]}
    record_audit(db, request, user, 'processing.jobs_read', None); db.commit()
    return result
