from PIL import Image
from datetime import datetime
from fastapi import HTTPException
from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
from pydantic import BaseModel
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from uuid import uuid4
import warnings

from ..adapters.crypto import decrypt
from ..adapters.crypto import decrypt_bytes
from ..adapters.crypto import encrypt
from ..adapters.crypto import encrypt_bytes
from ..adapters.objectstore import get_store
from ..core.exceptions import CiphertextIntegrityError
from .auth import user_from_request
from ..db.models import DocumentImport
from ..db.models import ExtractionJob
from ..db.models import PatientEvent
from ..db.models import StoredDocument
from ..db.models import User
from .audit import record_audit
from .authorization import require
from .authorization import scoped_patient


MAX_BYTES = 25 * 1024 * 1024


MAX_BODY = MAX_BYTES + 64 * 1024


MAX_PAGES = 500


MAX_PIXELS = 20_000_000


class DocumentOutput(BaseModel):
    id: str
    filename: str
    uploadedAt: datetime
    uploader: str
    pageCount: int
    sizeBytes: int
    mediaType: str
    reviewState: str = 'unreviewed'
    jobState: str = 'not_started'
    progress: int = 0
    processingMessage: str | None = None
    version: int = 1
    allowedActions: list[str] = ['download']


def output(db, row):
    meta = decrypt(row.metadata_payload, f'document-meta:{row.patient_id}:{row.id}')
    job = db.scalar(select(ExtractionJob).where(ExtractionJob.document_id == row.id))
    state = job.state if job else 'not_started'
    actions = ['download'] + (['extraction', 'review'] if state == 'completed' else [])
    return DocumentOutput(id=row.id, filename=meta['filename'], uploadedAt=row.created_at,
                          uploader=db.get(User, row.uploaded_by).display_name,
                          pageCount=row.page_count, sizeBytes=row.size_bytes, mediaType=row.media_type, jobState=state,
                          progress=int(job.completed_pages * 100 / row.page_count) if job else 0,
                          processingMessage=job.message if job else None, allowedActions=actions,
                          version=row.review_version, reviewState='imported' if db.get(DocumentImport, row.id) else 'in_review' if row.review_version > 1 else 'unreviewed')


def validate_file(raw, filename, declared_type):
    if not raw:
        raise HTTPException(422, 'The file is empty. Choose a PDF, JPEG or PNG.')
    name = PurePosixPath((filename or '').replace('\\', '/')).name
    name = ''.join(c for c in name if c.isprintable()).strip()
    if not name or len(name) > 240:
        raise HTTPException(422, 'Use a filename between 1 and 240 characters.')
    ext = PurePosixPath(name).suffix.lower()
    expected = {'.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}.get(ext)
    if not expected or declared_type not in {expected, 'application/octet-stream', None}:
        raise HTTPException(415, 'Choose a PDF, JPEG or PNG with its correct filename extension.')
    try:
        if expected == 'application/pdf':
            if not raw.startswith(b'%PDF-'):
                raise ValueError('Invalid PDF signature')
            reader = PdfReader(BytesIO(raw), strict=True)
            if reader.is_encrypted:
                raise HTTPException(422, 'Password-protected PDFs are not supported. Upload an unlocked copy.')
            pages = len(reader.pages)
            if not 1 <= pages <= MAX_PAGES:
                raise HTTPException(422, f'PDFs must contain between 1 and {MAX_PAGES} pages.')
        else:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(BytesIO(raw)) as image:
                    if image.format != ('PNG' if expected == 'image/png' else 'JPEG'):
                        raise ValueError('Image format mismatch')
                    if image.width * image.height > MAX_PIXELS:
                        raise HTTPException(422, 'Images must be no larger than 20 megapixels.')
                    if getattr(image, 'n_frames', 1) != 1:
                        raise HTTPException(422, 'Upload a single-page image, not an animated image.')
                    image.verify()
                with Image.open(BytesIO(raw)) as image:
                    image.load()  # Detect truncated image data before storing it.
            pages = 1
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, 'This file is damaged or is not a valid PDF, JPEG or PNG.') from None
    return name, expected, pages


def save_document(db, user, request, patient_id, raw, filename, content_type):
    user = user_from_request(request, db)
    require(user, 'documents:write')
    name, media_type, pages = validate_file(raw, filename, content_type)
    # Lock after reading the upload, then recheck scope and archive status.
    patient = scoped_patient(db, user, patient_id, clinical=True, lock=True)
    if patient.status != 'active':
        raise HTTPException(409, 'Reactivate the patient before uploading documents.')
    digest = sha256(raw).hexdigest()
    if db.scalar(select(StoredDocument.id).where(StoredDocument.patient_id == patient.id, StoredDocument.digest == digest)):
        raise HTTPException(409, 'This file is already stored for this patient. Use the existing original.')
    doc_id = str(uuid4())
    key = f'patients/{patient.id}/documents/{doc_id}/original'
    ciphertext = encrypt_bytes(raw, f'document:{patient.id}:{doc_id}')
    store = get_store()
    store.put(key, ciphertext, 'application/octet-stream')
    try:
        row = StoredDocument(id=doc_id, patient_id=patient.id, uploaded_by=user.id, digest=digest,
            metadata_payload=encrypt({'filename': name}, f'document-meta:{patient.id}:{doc_id}'),
            object_key=key, media_type=media_type,
            page_count=pages, size_bytes=len(raw))
        db.add(row)
        db.add(PatientEvent(patient_id=patient.id, actor_id=user.id, kind='document', title='Document uploaded', event_date=None, version=1))
        record_audit(db, request, user, 'document.upload', row.id)
        db.flush()
        result = output(db, row)
        db.commit()
    except IntegrityError:
        store.delete(key)
        db.rollback()
        raise HTTPException(409, 'This file is already stored for this patient.') from None
    except Exception:
        store.delete(key)
        raise
    return result


def original_bytes(row):
    try:
        data = get_store().get(row.object_key)
    except FileNotFoundError:
        raise HTTPException(503, 'Protected document could not be read.') from None
    raw = decrypt_bytes(data, f'document:{row.patient_id}:{row.id}')
    if len(raw) != row.size_bytes or sha256(raw).hexdigest() != row.digest:
        raise CiphertextIntegrityError('Document size or digest integrity failure.')
    return raw
