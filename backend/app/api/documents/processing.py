"""Durable extraction requests and protected access to draft page text."""
from uuid import UUID

from fastapi import APIRouter
from fastapi import Request

from ...services import processing as processing_service
from ..deps import CurrentUser
from ..deps import Db


router = APIRouter(tags=["Document processing"])


PREFIX = "/api/v1/patients/{patient_id}/documents/{document_id}"


@router.post(PREFIX + "/process", status_code=202)
def start(patient_id: UUID, document_id: UUID, user: CurrentUser, db: Db, request: Request):
    return processing_service.start(db, user, request, patient_id, document_id)


@router.post(PREFIX + "/retry", status_code=202)
def retry(patient_id: UUID, document_id: UUID, user: CurrentUser, db: Db, request: Request):
    return processing_service.retry(db, user, request, patient_id, document_id)


@router.post(PREFIX + "/cancel")
def cancel(patient_id: UUID, document_id: UUID, user: CurrentUser, db: Db, request: Request):
    return processing_service.cancel(db, user, request, patient_id, document_id)


@router.post(PREFIX + "/withdraw")
def withdraw(patient_id: UUID, document_id: UUID, user: CurrentUser, db: Db, request: Request):
    return processing_service.withdraw(db, user, request, patient_id, document_id)


@router.get(PREFIX + "/pages")
def pages(patient_id: UUID, document_id: UUID, user: CurrentUser, db: Db, request: Request):
    return processing_service.pages(db, user, request, patient_id, document_id)


@router.get("/api/v1/admin/operations/jobs")
def jobs(user: CurrentUser, db: Db, request: Request):
    return processing_service.jobs(db, user, request)
