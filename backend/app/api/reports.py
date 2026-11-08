from fastapi import APIRouter
from fastapi import Request
from fastapi import Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import aliased
from uuid import UUID

from ..db.models import ClinicalNote
from ..services.audit import record_audit
from ..services.authorization import require
from ..services.authorization import scoped_patient
from ..services.reports import create_preview
from ..services.reports import export_pdf
from ..services.summaries import snapshot
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
    require(user, "reports:write")
    patient = scoped_patient(db, user, patient_id, clinical=True)
    child = aliased(ClinicalNote)
    rows = db.scalars(
        select(ClinicalNote)
        .where(
            ClinicalNote.patient_id == patient.id,
            ClinicalNote.state == "finalized",
            ~select(child.id).where(child.parent_id == ClinicalNote.id, child.state == "finalized").exists(),
        )
        .order_by(ClinicalNote.created_at)
    ).all()
    items = [{k: v for k, v in snapshot(row).items() if k != "text"} for row in rows]
    record_audit(db, request, user, "report.sources_read", patient.id)
    db.commit()
    return {"items": items}


@router.post("/preview", status_code=200)
def preview(patient_id: UUID, body: PreviewPayload, user: CurrentUser, db: Db, request: Request):
    require(user, "reports:write")
    patient = scoped_patient(db, user, patient_id, clinical=True)
    manifest = create_preview(db, user, patient, [s.model_dump() for s in body.sourceVersions])
    record_audit(db, request, user, "report.preview", manifest["id"])
    db.commit()
    return manifest


@router.get("/{report_id}/export")
def export(patient_id: UUID, report_id: UUID, user: CurrentUser, db: Db, request: Request):
    require(user, "reports:write")
    patient = scoped_patient(db, user, patient_id, clinical=True)
    pdf = export_pdf(db, user, request, patient, report_id)
    return Response(
        pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="sanctum-report.pdf"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
