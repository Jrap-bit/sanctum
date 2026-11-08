"""Explicit clinician-confirmed medications; values are never inferred from prose."""
from fastapi import APIRouter
from fastapi import Request
from pydantic import Field
from pydantic import field_validator
from typing import Literal
from uuid import UUID

from ..services import medications as medications_service
from .deps import CurrentUser
from .deps import Db
from .schemas import Input
from .schemas import VersionInput


router = APIRouter(prefix="/api/v1/patients/{patient_id}/medications", tags=["Confirmed medications"])


class MedicationInput(Input):
    sourceId: UUID
    sourceVersion: int = Field(ge=1)
    medicationName: str = Field(min_length=1, max_length=160)
    changeStatus: Literal["changed", "no_change", "uncertain"]

    @field_validator("medicationName")
    @classmethod
    def clean_name(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("Enter the medication name as documented.")
        return value

    quotation: str = Field(min_length=3, max_length=2000)
    confirmed: Literal[True]


class Withdrawal(VersionInput):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def clean(cls, value):
        if not value.strip():
            raise ValueError("Explain why this medication is being withdrawn.")
        return value.strip()


@router.get("")
def list_medications(patient_id: UUID, user: CurrentUser, db: Db, request: Request):
    return medications_service.list_medications(db, user, request, patient_id)


@router.get("/sources")
def sources(patient_id: UUID, user: CurrentUser, db: Db, request: Request):
    return medications_service.sources(db, user, request, patient_id)


@router.post("", status_code=201)
def create_medication(patient_id: UUID, data: MedicationInput, user: CurrentUser, db: Db, request: Request):
    return medications_service.create_medication(db, user, request, patient_id, data)


@router.post("/{medication_id}/withdraw")
def withdraw(patient_id: UUID, medication_id: UUID, data: Withdrawal, user: CurrentUser, db: Db, request: Request):
    return medications_service.withdraw(db, user, request, patient_id, medication_id, data)
