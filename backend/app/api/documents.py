"""Patient-scoped encrypted originals; OCR/review is a separate next stage."""
from urllib.parse import quote
from uuid import UUID
from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from ..db.models import StoredDocument
from ..services import documents as document_service
from ..services.audit import record_audit
from ..services.authorization import require, scoped_patient
from ..services.documents import DocumentOutput, original_bytes, output
from .deps import CurrentUser, Db


router = APIRouter(prefix="/api/v1/patients/{patient_id}/documents", tags=["Documents"])


class MemoryMultipartParser(MultiPartParser):
    spool_max_size = document_service.MAX_BODY + 1


@router.post("", response_model=DocumentOutput, status_code=201)
async def upload_document(patient_id: UUID, user: CurrentUser, db: Db, request: Request):
    require(user, "documents:write")
    patient = scoped_patient(db, user, patient_id, clinical=True)
    if patient.status != "active":
        raise HTTPException(409, "Reactivate the patient before uploading documents.")
    db.rollback()
    if not request.headers.get("content-type", "").lower().startswith("multipart/form-data;"):
        raise HTTPException(415, "Send one file as multipart form data.")

    async def bounded_stream():
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > document_service.MAX_BODY:
                raise HTTPException(413, "Choose a file no larger than 25 MB.")
            yield chunk

    try:
        form = await MemoryMultipartParser(request.headers, bounded_stream(), max_files=1, max_fields=0).parse()
    except MultiPartException:
        raise HTTPException(422, "Send exactly one file in the file field.") from None
    try:
        file = form.get("file")
        if not isinstance(file, UploadFile) or len(form.multi_items()) != 1:
            raise HTTPException(422, "Send exactly one file in the file field.")
        raw = await file.read(document_service.MAX_BYTES + 1)
        if len(raw) > document_service.MAX_BYTES:
            raise HTTPException(413, "Choose a file no larger than 25 MB.")
        return await run_in_threadpool(document_service.save_document, db, user, request, patient_id, raw, file.filename, file.content_type)
    finally:
        await form.close()


@router.get("", response_model=dict[str, list[DocumentOutput]])
def list_documents(patient_id: UUID, user: CurrentUser, db: Db, request: Request):
    patient = scoped_patient(db, user, patient_id, clinical=True)
    rows = db.scalars(
        select(StoredDocument)
        .where(StoredDocument.patient_id == patient.id)
        .order_by(StoredDocument.created_at.desc(), StoredDocument.id)
    ).all()
    result = {"items": [output(db, row, user=user) for row in rows]}
    record_audit(db, request, user, "document.list", patient.id)
    db.commit()
    return result


@router.get("/{document_id}/original")
def download_document(patient_id: UUID, document_id: UUID, user: CurrentUser, db: Db, request: Request):
    patient = scoped_patient(db, user, patient_id, clinical=True)
    row = db.scalar(
        select(StoredDocument).where(
            StoredDocument.id == str(document_id),
            StoredDocument.patient_id == patient.id,
        )
    )
    if row is None:
        raise HTTPException(404, "Document unavailable.")
    meta = output(db, row, user=user)
    raw = original_bytes(row)
    record_audit(db, request, user, "document.download", row.id)
    db.commit()
    return Response(
        raw,
        media_type=row.media_type,
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(meta.filename, safe=""),
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
