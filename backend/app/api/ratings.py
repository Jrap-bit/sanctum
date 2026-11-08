"""Explicit clinician-confirmed ratings; values are never inferred from prose."""
from fastapi import APIRouter
from fastapi import Request
from pydantic import Field
from pydantic import field_validator
from typing import Literal
from uuid import UUID

from ..services import ratings as ratings_service
from .deps import CurrentUser
from .deps import Db
from .schemas import Input
from .schemas import VersionInput


router = APIRouter(prefix="/api/v1/patients/{patient_id}/ratings", tags=["Confirmed ratings"])


class RatingInput(Input):
    sourceId: UUID
    sourceVersion: int = Field(ge=1)
    scaleName: str = Field(min_length=1, max_length=100)
    value: float = Field(ge=0, le=10, allow_inf_nan=False)
    higherMeans: Literal["more_difficulty", "less_difficulty", "unknown"]
    confirmed: Literal[True]

    @field_validator("scaleName")
    @classmethod
    def clean(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("Name the scale as documented in the source.")
        return value


class Withdrawal(VersionInput):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def clean(cls, value):
        if not value.strip():
            raise ValueError("Explain why this rating is being withdrawn.")
        return value.strip()


@router.get("")
def list_ratings(patient_id: UUID, user: CurrentUser, db: Db, request: Request):
    return ratings_service.list_ratings(db, user, request, patient_id)


@router.get("/sources")
def sources(patient_id: UUID, user: CurrentUser, db: Db, request: Request):
    return ratings_service.sources(db, user, request, patient_id)


@router.post("", status_code=201)
def create_rating(patient_id: UUID, data: RatingInput, user: CurrentUser, db: Db, request: Request):
    return ratings_service.create_rating(db, user, request, patient_id, data)


@router.post("/{rating_id}/withdraw")
def withdraw(patient_id: UUID, rating_id: UUID, data: Withdrawal, user: CurrentUser, db: Db, request: Request):
    return ratings_service.withdraw(db, user, request, patient_id, rating_id, data)
