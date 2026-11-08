"""Patient-scoped encrypted originals; OCR/review is a separate next stage."""
from uuid import UUID

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException
from starlette.formparsers import MultiPartParser

from ..services import documents as document_service
from ..services.documents import DocumentOutput
from .deps import CurrentUser
from .deps import Db


router = APIRouter(prefix="/api/v1/patients/{patient_id}/documents", tags=["Documents"])


class MemoryMultipartParser(MultiPartParser):
    spool_max_size = document_service.MAX_BODY + 1


@router.post("", response_model=DocumentOutput, status_code=201)
async def upload_document(patient_id: UUID, user: CurrentUser, db: Db, request: Request):
    document_service.prepare_upload(db, user, patient_id)
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
        return await run_in_threadpool(
            document_service.save_document,
            db,
            user,
            request,
            patient_id,
            raw,
            file.filename,
            file.content_type,
        )
    finally:
        await form.close()


@router.get("", response_model=dict[str, list[DocumentOutput]])
def list_documents(patient_id: UUID, user: CurrentUser, db: Db, request: Request):
    return document_service.list_documents(db, user, request, patient_id)


@router.get("/{document_id}/original")
def download_document(patient_id: UUID, document_id: UUID, user: CurrentUser, db: Db, request: Request):
    return document_service.download_document(db, user, request, patient_id, document_id)
