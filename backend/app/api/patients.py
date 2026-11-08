"""Patient profiles and their overview. All clinical access is checked on the server."""
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from fastapi import Request
from pydantic import Field
from pydantic import field_validator

from ..services import patients as patients_service
from ..services.patients import PatientList
from ..services.patients import PatientOutput
from ..services.patients import clinic_today
from .deps import CurrentUser
from .deps import Db
from .schemas import Input
from .schemas import VersionInput


router = APIRouter(prefix="/api/v1", tags=["Patients"])


class ProfileFields(Input):
    displayName: str = Field(min_length=1, max_length=160)
    dateOfBirth: date | None = None

    @field_validator("displayName")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("A patient name is required.")
        return value.strip()

    @field_validator("dateOfBirth")
    @classmethod
    def valid_birth_date(cls, value):
        if value and value > clinic_today():
            raise ValueError("Date of birth cannot be in the future.")
        return value


class CreatePatient(ProfileFields):
    initialPractitionerId: UUID | None = None


class UpdatePatient(Input):
    expectedVersion: int = Field(ge=1)
    displayName: str | None = Field(default=None, min_length=1, max_length=160)
    dateOfBirth: date | None = None

    @field_validator("displayName")
    @classmethod
    def clean_name(cls, value):
        if value is None or not value.strip():
            raise ValueError("A patient name is required.")
        return value.strip()

    @field_validator("dateOfBirth")
    @classmethod
    def valid_birth_date(cls, value):
        return ProfileFields.valid_birth_date(value)


class TaskInput(Input):
    title: str = Field(min_length=1, max_length=240)
    details: str = Field(default="", max_length=4000)
    dueDate: date | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value):
        if not value.strip():
            raise ValueError("A follow-up title is required.")
        return value.strip()


class TaskUpdate(Input):
    state: Literal["completed", "cancelled"]


@router.get("/patients", response_model=PatientList)
def list_patients(
    user: CurrentUser,
    db: Db,
    request: Request,
    status: Literal["active", "archived"] = "active",
    q: str = "",
):
    return patients_service.list_patients(db, user, request, status=status, q=q)


@router.post("/patients", response_model=PatientOutput, status_code=201)
def create_patient(data: CreatePatient, user: CurrentUser, db: Db, request: Request):
    return patients_service.create_patient(db, user, request, data)


@router.get("/patients/{patient_id}", response_model=PatientOutput)
def get_patient(patient_id: UUID, user: CurrentUser, db: Db, request: Request):
    return patients_service.get_patient(db, user, request, patient_id)


@router.patch("/patients/{patient_id}", response_model=PatientOutput)
def update_patient(patient_id: UUID, data: UpdatePatient, user: CurrentUser, db: Db, request: Request):
    return patients_service.update_patient(db, user, request, patient_id, data)


@router.post("/patients/{patient_id}/archive", response_model=PatientOutput)
def archive_patient(patient_id: UUID, data: VersionInput, user: CurrentUser, db: Db, request: Request):
    return patients_service.archive_patient(db, user, request, patient_id, data)


@router.post("/patients/{patient_id}/reactivate", response_model=PatientOutput)
def reactivate_patient(patient_id: UUID, data: VersionInput, user: CurrentUser, db: Db, request: Request):
    return patients_service.reactivate_patient(db, user, request, patient_id, data)


@router.get("/patients/{patient_id}/timeline")
def timeline(patient_id: UUID, user: CurrentUser, db: Db, request: Request):
    return patients_service.timeline(db, user, request, patient_id)


@router.get("/patients/{patient_id}/follow-ups")
def list_tasks(patient_id: UUID, user: CurrentUser, db: Db, request: Request):
    return patients_service.list_tasks(db, user, request, patient_id)


@router.post("/patients/{patient_id}/follow-ups", status_code=201)
def create_task(patient_id: UUID, data: TaskInput, user: CurrentUser, db: Db, request: Request):
    return patients_service.create_task(db, user, request, patient_id, data)


@router.patch("/patients/{patient_id}/follow-ups/{task_id}")
def update_task(patient_id: UUID, task_id: UUID, data: TaskUpdate, user: CurrentUser, db: Db, request: Request):
    return patients_service.update_task(db, user, request, patient_id, task_id, data)
