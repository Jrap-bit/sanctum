from fastapi import HTTPException
from sqlalchemy import select

from ..db.models import ClinicalGrant
from ..db.models import Patient
from ..db.models import PatientAccess


def require(user, capability):
    if capability not in user.capabilities:
        raise HTTPException(403, "This action is outside your permissions.")


def access_ids(user,write=False):
    grants=select(ClinicalGrant.patient_id).where(ClinicalGrant.subject_id==user.id,ClinicalGrant.state=='approved')
    if write:grants=grants.where(ClinicalGrant.capability=='clinical:write')
    return select(PatientAccess.patient_id).where(PatientAccess.user_id==user.id).union(grants)


def has_access(db, user, patient_id, write=False, *, allow_deleting=False):
    statement = select(Patient.id).where(Patient.id == str(patient_id), Patient.id.in_(access_ids(user, write)))
    if not allow_deleting:
        statement = statement.where(Patient.status != "deleting")
    return db.scalar(statement) is not None


def scoped_patient(db, user, patient_id, *, clinical=False, write=False, lock=False):
    require(user, "clinical:write" if write else "clinical:read" if clinical else "patients:read")
    statement = select(Patient).where(Patient.id == str(patient_id), Patient.status != "deleting")
    # Profile administrators get identity access only, never implicit clinical access.
    if clinical or write or "users:manage" not in user.capabilities:
        statement = statement.where(Patient.id.in_(access_ids(user)))
    if (write or lock) and (clinical or write or 'users:manage' not in user.capabilities):
        statement=statement.where(Patient.id.in_(access_ids(user,write=True)))
    if lock:
        statement = statement.with_for_update()
    patient = db.scalar(statement)
    if patient is None or patient.status == "deleting":
        raise HTTPException(404, "Patient unavailable.")
    # Recheck after acquiring the patient lock: a grant may have been revoked
    # while this transaction waited for another writer.
    if lock and (clinical or write or "users:manage" not in user.capabilities) and not has_access(db,user,patient.id,write=True):
        raise HTTPException(404, "Patient unavailable.")
    return patient
