"""Source-version-bound AI drafts and independent clinician review of prose/facts."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from fastapi import Request
from pydantic import Field
from pydantic import model_validator

from ..core.config import get_settings
from ..services import summaries as summaries_service
from .deps import CurrentUser
from .deps import Db
from .schemas import Input
from .schemas import VersionInput


router = APIRouter(tags=["AI summaries"])


PREFIX = "/api/v1/patients/{patient_id}/summaries"


class SourceVersion(Input):
    id: UUID
    version: int = Field(ge=1)
    type: Literal["session"]


class CreateSummary(Input):
    kind: Literal["single_session", "longitudinal"]
    sourceVersions: list[SourceVersion] = Field(min_length=1, max_length=30)
    requestKey: UUID
    model: str | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.model is not None and self.model not in get_settings().llm_models:
            raise ValueError("Unknown model.")
        if self.kind == "single_session" and len(self.sourceVersions) != 1:
            raise ValueError("Choose one source for a single-session summary.")
        if len({s.id for s in self.sourceVersions}) != len(self.sourceVersions):
            raise ValueError("Choose each source once.")
        return self


class SummaryReview(VersionInput):
    decision: Literal["accept", "edit_accept", "reject"]
    text: str | None = Field(default=None, max_length=20000)

    @model_validator(mode="after")
    def valid(self):
        if self.decision == "edit_accept" and not (self.text or "").strip():
            raise ValueError("Enter the reviewed summary text.")
        return self


class FactReview(VersionInput):
    label: Literal["concern", "observation", "intervention", "medication_reported", "follow_up", "other"] | None = None
    decision: Literal["confirm", "correct", "reject"]
    text: str | None = Field(default=None, max_length=1200)
    assertion: Literal["present", "denied", "possible", "unknown"] | None = None
    temporality: Literal["current", "historical", "unknown"] | None = None
    subject: Literal["patient", "other", "unknown"] | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.decision == "correct" and (
            not (self.text or "").strip()
            or not self.assertion
            or not self.temporality
            or not self.subject
        ):
            raise ValueError("Corrected facts need text, assertion, time and subject.")
        return self


@router.get("/api/v1/ai/status")
def model_status(user: CurrentUser, model: str | None = None):
    return summaries_service.model_status(user, model)


@router.get(PREFIX + "/eligible-sources")
def eligible(patient_id: UUID, user: CurrentUser, db: Db, request: Request):
    return summaries_service.eligible(db, user, request, patient_id)


@router.post(PREFIX, status_code=202)
def create(patient_id: UUID, data: CreateSummary, user: CurrentUser, db: Db, request: Request):
    return summaries_service.create(db, user, request, patient_id, data)


@router.get(PREFIX)
def list_summaries(patient_id: UUID, user: CurrentUser, db: Db, request: Request):
    return summaries_service.list_summaries(db, user, request, patient_id)


@router.get(PREFIX + "/generation-jobs")
def patient_jobs(patient_id: UUID, user: CurrentUser, db: Db, request: Request):
    return summaries_service.patient_jobs(db, user, request, patient_id)


@router.get(PREFIX + "/{summary_id}")
def get_summary(patient_id: UUID, summary_id: UUID, user: CurrentUser, db: Db, request: Request):
    return summaries_service.get_summary(db, user, request, patient_id, summary_id)


@router.post(PREFIX + "/{summary_id}/review")
def review_summary(patient_id: UUID, summary_id: UUID, data: SummaryReview, user: CurrentUser, db: Db, request: Request):
    return summaries_service.review_summary(db, user, request, patient_id, summary_id, data)


@router.post(PREFIX + "/{summary_id}/facts/{fact_id}/review")
def review_fact(patient_id: UUID, summary_id: UUID, fact_id: UUID, data: FactReview, user: CurrentUser, db: Db, request: Request):
    return summaries_service.review_fact(db, user, request, patient_id, summary_id, fact_id, data)


@router.get("/api/v1/jobs/{job_id}")
def get_job(job_id: UUID, user: CurrentUser, db: Db, request: Request):
    return summaries_service.get_job(db, user, request, job_id)


@router.post("/api/v1/jobs/{job_id}/cancel")
def cancel_job(job_id: UUID, user: CurrentUser, db: Db, request: Request):
    return summaries_service.cancel_job(db, user, request, job_id)


@router.post("/api/v1/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: UUID, user: CurrentUser, db: Db, request: Request):
    return summaries_service.retry_job(db, user, request, job_id)
