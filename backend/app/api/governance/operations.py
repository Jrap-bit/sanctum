from fastapi import APIRouter
from fastapi import Request
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator

from ...services import operations as operations_service
from ..deps import CurrentUser
from ..deps import Db


router = APIRouter(prefix="/api/v1", tags=["Operations"])


class DeletePatientRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1000)
    expectedVersion: int

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value):
        if not value.strip():
            raise ValueError("Reason cannot be blank.")
        return value.strip()


class EmptyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    packageId: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value):
        if not value.strip():
            raise ValueError("Reason cannot be blank.")
        return value.strip()


@router.delete("/patients/{patient_id}")
def delete_patient_endpoint(
    patient_id: str,
    data: DeletePatientRequest,
    user: CurrentUser,
    db: Db,
    request: Request,
):
    return operations_service.delete_patient_endpoint(db, user, request, patient_id, data)


@router.get("/admin/operations/backups")
def list_backups(user: CurrentUser, db: Db):
    return operations_service.list_backups(db, user)


@router.post("/admin/operations/backups", status_code=201)
def trigger_backup(user: CurrentUser, db: Db, data: EmptyBody = EmptyBody()):
    return operations_service.trigger_backup(db, user)


@router.post("/admin/operations/restore/validate")
def validate_restore(data: RestoreRequest, user: CurrentUser, db: Db, request: Request):
    return operations_service.validate_restore_request(db, user, request, data)


@router.post("/admin/operations/restore")
def perform_restore(data: RestoreRequest, user: CurrentUser, db: Db, request: Request):
    return operations_service.perform_restore_request(db, user, request, data)
