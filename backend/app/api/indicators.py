"""DT-03: deterministic follow-up results with retained source snapshots."""
from fastapi import APIRouter
from fastapi import Request
from pydantic import Field
from typing import Literal
from uuid import UUID

from ..services import indicators as indicators_service
from .deps import CurrentUser
from .deps import Db
from .schemas import VersionInput


router = APIRouter(prefix="/api/v1/patients/{patient_id}/indicators", tags=["Indicators"])


@router.get("")
def get_indicators(patient_id: UUID, user: CurrentUser, db: Db, request: Request):
    return indicators_service.get_indicators(db, user, request, patient_id)


@router.post("/evaluate")
def evaluate(patient_id: UUID, user: CurrentUser, db: Db, request: Request):
    return indicators_service.evaluate(db, user, request, patient_id)


class Review(VersionInput):
    evaluationId: UUID
    decision: Literal["acknowledge", "dismiss"]
    comment: str | None = Field(default=None, max_length=2000)


@router.post("/{indicator_id}/review")
def review_indicator(patient_id: UUID, indicator_id: UUID, data: Review, user: CurrentUser, db: Db, request: Request):
    return indicators_service.review_indicator(db, user, request, patient_id, indicator_id, data)


@router.get("/history/runs")
def history(patient_id: UUID, user: CurrentUser, db: Db, request: Request):
    return indicators_service.history(db, user, request, patient_id)


@router.get("/history/runs/{run_id}")
def historical_run(patient_id: UUID, run_id: UUID, user: CurrentUser, db: Db, request: Request):
    return indicators_service.historical_run(db, user, request, patient_id, run_id)
