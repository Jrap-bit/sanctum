"""Explicit clinician-confirmed concerns; values are never inferred from prose."""
from fastapi import APIRouter
from fastapi import Request
from pydantic import Field
from pydantic import field_validator
from typing import Literal
from uuid import UUID

from ..services import concerns as concerns_service
from .deps import CurrentUser
from .deps import Db
from .schemas import Input
from .schemas import VersionInput


router = APIRouter(prefix="/api/v1/patients/{patient_id}/concerns", tags=["Confirmed concerns"])


class ConcernInput(Input):
    sourceId: UUID
    sourceVersion: int = Field(ge=1)
    concernCode: Literal[
        "sleep_difficulty",
        "anxiety",
        "low_mood",
        "concentration_difficulty",
        "fatigue",
        "irritability",
        "social_avoidance",
        "work_stress",
    ]
    assertion: Literal["present", "denied", "possible", "unknown"]
    temporality: Literal["current", "historical", "unknown"]
    subject: Literal["patient", "other", "unknown"]
    quotation: str = Field(min_length=3, max_length=2000)
    confirmed: Literal[True]


class Withdrawal(VersionInput):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def clean(cls, value):
        if not value.strip():
            raise ValueError("Explain why this concern is being withdrawn.")
        return value.strip()


@router.get("")
def list_concerns(patient_id: UUID, user: CurrentUser, db: Db, request: Request):
    return concerns_service.list_concerns(db, user, request, patient_id)


@router.get("/sources")
def sources(patient_id: UUID, user: CurrentUser, db: Db, request: Request):
    return concerns_service.sources(db, user, request, patient_id)


@router.post("", status_code=201)
def create_concern(patient_id: UUID, data: ConcernInput, user: CurrentUser, db: Db, request: Request):
    return concerns_service.create_concern(db, user, request, patient_id, data)


@router.post("/{concern_id}/withdraw")
def withdraw(patient_id: UUID, concern_id: UUID, data: Withdrawal, user: CurrentUser, db: Db, request: Request):
    return concerns_service.withdraw(db, user, request, patient_id, concern_id, data)
