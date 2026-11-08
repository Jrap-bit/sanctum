from uuid import UUID

from fastapi import APIRouter
from fastapi import Request
from fastapi import Response
from pydantic import Field

from ..services import reports as reports_service
from .deps import CurrentUser
from .deps import Db
from .schemas import Input


router = APIRouter(prefix="/api/v1/patients/{patient_id}/reports", tags=["Reports"])


class SourceVersionItem(Input):
    id: str
    version: int
    type: str


class PreviewPayload(Input):
    sourceVersions: list[SourceVersionItem] = Field(min_length=1, max_length=100)


@router.get("/eligible-sources")
def eligible_sources(patient_id: UUID, user: CurrentUser, db: Db, request: Request):
    return reports_service.eligible_sources(db, user, request, patient_id)


@router.post("/preview", status_code=200)
def preview(patient_id: UUID, body: PreviewPayload, user: CurrentUser, db: Db, request: Request):
    return reports_service.preview(db, user, request, patient_id, body)


@router.get("/{report_id}/export")
def export(patient_id: UUID, report_id: UUID, user: CurrentUser, db: Db, request: Request):
    pdf = reports_service.export(db, user, request, patient_id, report_id)
    return Response(
        pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="sanctum-report.pdf"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
