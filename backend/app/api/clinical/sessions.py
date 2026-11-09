"""Session workflow: draft → finalized → a separate amendment draft."""
from datetime import date
from uuid import UUID

from fastapi import APIRouter
from fastapi import Request
from pydantic import Field
from pydantic import field_validator

from ...services import sessions as sessions_service
from ...services.patients import clinic_today
from ...services.sessions import NoteField
from ...services.sessions import SessionOutput
from ..deps import CurrentUser
from ..deps import Db
from ..schemas import Input
from ..schemas import VersionInput


router = APIRouter(prefix="/api/v1/patients/{patient_id}/sessions", tags=["Session notes"])


class SessionDate(Input):
    eventDate: date | None = None

    @field_validator("eventDate")
    @classmethod
    def validate_date(cls, value):
        if value and value > clinic_today():
            raise ValueError("Session date cannot be in the future.")
        return value


class SaveDraft(SessionDate):
    # The existing editor sends a complete content snapshot on each save.
    expectedVersion: int = Field(ge=1)
    text: str = Field(max_length=100000)
    concerns: list[NoteField] = Field(max_length=100)
    observations: list[NoteField] = Field(max_length=100)
    interventions: list[NoteField] = Field(max_length=100)
    medicationReported: list[NoteField] = Field(max_length=100)


class AmendmentInput(VersionInput):
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def nonempty_reason(cls, value):
        if not value.strip():
            raise ValueError("Explain why the note needs an amendment.")
        return value.strip()


@router.post("", response_model=SessionOutput, status_code=201)
def create_session(patient_id: UUID, data: SessionDate, user: CurrentUser, db: Db, request: Request):
    return sessions_service.create_session(db, user, request, patient_id, data)


@router.get("/{session_id}", response_model=SessionOutput)
def get_session(patient_id: UUID, session_id: UUID, user: CurrentUser, db: Db, request: Request):
    return sessions_service.get_session(db, user, request, patient_id, session_id)


@router.patch("/{session_id}", response_model=SessionOutput)
def save_draft(patient_id: UUID, session_id: UUID, data: SaveDraft, user: CurrentUser, db: Db, request: Request):
    return sessions_service.save_draft(db, user, request, patient_id, session_id, data)


@router.post("/{session_id}/finalize", response_model=SessionOutput)
def finalize_session(patient_id: UUID, session_id: UUID, data: VersionInput, user: CurrentUser, db: Db, request: Request):
    return sessions_service.finalize_session(db, user, request, patient_id, session_id, data)


@router.post("/{session_id}/amendments", response_model=SessionOutput, status_code=201)
def create_amendment(patient_id: UUID, session_id: UUID, data: AmendmentInput, user: CurrentUser, db: Db, request: Request):
    return sessions_service.create_amendment(db, user, request, patient_id, session_id, data)
