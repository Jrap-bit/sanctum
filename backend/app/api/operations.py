from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from ..core.security import passwords
from ..db.models import BackupRecord, Patient
from ..services.audit import record_audit
from ..services.authorization import has_access, require
from ..services.operations import (
    create_backup,
    delete_patient,
    format_manifest_summary,
    restore_package,
    validate_package,
    PackageInvalid,
)
from .deps import CurrentUser, Db


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
    if "patients:delete" not in user.capabilities or "users:manage" not in user.capabilities:
        raise HTTPException(403, "This action is outside your permissions.")
    if not has_access(db, user, patient_id, allow_deleting=True):
        raise HTTPException(404, "Patient unavailable.")
    patient = db.scalar(select(Patient).where(Patient.id == str(patient_id)).with_for_update())
    if patient is None:
        raise HTTPException(404, "Patient unavailable.")
    if not passwords.verify(data.password, user.password_hash):
        raise HTTPException(403, "Password confirmation failed.")
    if patient.status != "deleting":
        if patient.version != data.expectedVersion:
            raise HTTPException(409, "A newer version exists. Refresh and try again.")
    return delete_patient(db, request, user, patient, data.reason)


@router.get("/admin/operations/backups")
def list_backups(user: CurrentUser, db: Db):
    require(user, "operations:manage")
    records = db.scalars(select(BackupRecord).order_by(BackupRecord.created_at.desc())).all()
    items = []
    for r in records:
        items.append({
            "id": r.id,
            "createdAt": r.created_at.isoformat(),
            "scope": "Database and original documents",
            "verified": r.verified,
            "manifest": format_manifest_summary(r.manifest),
        })
    return {"items": items}


@router.post("/admin/operations/backups", status_code=201)
def trigger_backup(user: CurrentUser, db: Db, data: EmptyBody = EmptyBody()):
    require(user, "operations:manage")
    record = create_backup(db, actor_id=user.id)
    return {
        "id": record.id,
        "createdAt": record.created_at.isoformat(),
        "scope": "Database and original documents",
        "verified": record.verified,
        "manifest": format_manifest_summary(record.manifest),
    }


@router.post("/admin/operations/restore/validate")
def validate_restore(data: RestoreRequest, user: CurrentUser, db: Db, request: Request):
    require(user, "operations:manage")
    if not passwords.verify(data.password, user.password_hash):
        raise HTTPException(403, "Password confirmation failed.")
    backup = db.get(BackupRecord, data.packageId)
    if backup is None:
        raise HTTPException(404, "Backup not found.")
    path = Path(backup.path)
    if not path.is_file():
        raise HTTPException(404, "Backup file not found.")
    package_bytes = path.read_bytes()
    try:
        manifest = validate_package(package_bytes, db)
        summary = format_manifest_summary(manifest)
        record_audit(db, request, user, "backup.validated", backup.id)
        db.commit()
        return {"valid": True, "manifest": summary}
    except PackageInvalid:
        record_audit(db, request, user, "backup.rejected", backup.id)
        db.commit()
        raise HTTPException(422, "This backup failed verification. Nothing was changed.")


@router.post("/admin/operations/restore")
def perform_restore(data: RestoreRequest, user: CurrentUser, db: Db, request: Request):
    require(user, "operations:manage")
    if not passwords.verify(data.password, user.password_hash):
        raise HTTPException(403, "Password confirmation failed.")
    backup = db.get(BackupRecord, data.packageId)
    if backup is None:
        raise HTTPException(404, "Backup not found.")
    path = Path(backup.path)
    if not path.is_file():
        raise HTTPException(404, "Backup file not found.")
    package_bytes = path.read_bytes()
    try:
        restore_package(db, package_bytes)
        record_audit(db, request, user, "backup.restored", backup.id)
        db.commit()
        return {"restored": True}
    except PackageInvalid:
        record_audit(db, request, user, "backup.rejected", backup.id)
        db.commit()
        raise HTTPException(422, "This backup failed verification. Nothing was changed.")
