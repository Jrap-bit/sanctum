from uuid import UUID
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from ..adapters.crypto import decrypt
from ..adapters.crypto import encrypt
from ..db.models import ClinicalGrant
from ..db.models import Patient
from ..db.models import User
from ..db.models import now
from .audit import record_audit
from .authorization import has_access
from .authorization import require


def result(db, user, row):
    payload = decrypt(row.payload, f"grant:{row.id}")
    person = db.get(User, row.subject_id)
    approver = db.get(User, row.approver_id) if row.approver_id else None
    independent_reviewer = (
        "grants:approve" in user.capabilities
        and user.id != row.subject_id
        and user.id != row.requester_id
    )
    actions = []
    if independent_reviewer and row.state == "pending":
        actions = ["approve", "deny"]
    if independent_reviewer and row.state == "approved":
        actions = ["revoke"]
    if row.subject_id == user.id and row.state == "pending":
        actions = ["cancel"]
    return {
        "id": row.id,
        "version": row.version,
        "patientId": row.patient_id,
        "subjectId": row.subject_id,
        "subjectName": person.display_name,
        "requesterId": row.requester_id,
        "capability": row.capability,
        "state": row.state,
        "createdAt": row.created_at,
        "approverName": approver.display_name if approver else None,
        "reviewedAt": row.reviewed_at,
        **payload,
        "allowedActions": actions,
    }


def locked(db, user, gid, expected):
    row = db.get(ClinicalGrant, str(gid))
    if row is None or ("grants:approve" not in user.capabilities and row.subject_id != user.id):
        raise HTTPException(404, "Request unavailable.")
    # Match clinical write lock order; approval/revocation serialize with patient writes.
    db.scalar(select(Patient).where(Patient.id == row.patient_id).with_for_update())
    row = db.scalar(
        select(ClinicalGrant)
        .where(ClinicalGrant.id == str(gid))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row.version != expected:
        raise HTTPException(409, "This request changed. Refresh before deciding.")
    return row


def save(db, request, user, row, action, comment):
    payload = decrypt(row.payload, f"grant:{row.id}")
    payload["history"].append(
        {
            "action": action,
            "comment": comment,
            "actor": user.display_name,
            "actorId": user.id,
            "at": now().isoformat(),
        }
    )
    row.payload = encrypt(payload, f"grant:{row.id}")
    row.version += 1
    record_audit(db, request, user, "grant." + action, row.id)
    db.flush()
    output = result(db, user, row)
    db.commit()
    return output


def independent(user, row):
    require(user, "grants:approve")
    if user.id in {row.requester_id, row.subject_id}:
        raise HTTPException(403, "You cannot approve or manage your own access request.")


def listing(db, user, request):
    if not {"grants:request", "grants:approve"} & set(user.capabilities):
        raise HTTPException(403, "Access requests are unavailable for this account.")
    query = select(ClinicalGrant).order_by(ClinicalGrant.created_at.desc())
    if "grants:approve" not in user.capabilities:
        query = query.where(ClinicalGrant.subject_id == user.id)
    output = {
        "items": [result(db, user, row) for row in db.scalars(query)],
        "canRequest": "grants:request" in user.capabilities and "clinical:read" in user.capabilities,
        "canRequestWrite": "clinical:write" in user.capabilities,
    }
    record_audit(db, request, user, "grant.list", None)
    db.commit()
    return output


def create(db, user, request, data):
    require(user, "grants:request")
    require(user, data.capability)
    patient = db.scalar(
        select(Patient)
        .where(Patient.id == str(data.patientId), Patient.status == "active")
        .with_for_update()
    )
    if patient is None:
        raise HTTPException(404, "Patient unavailable. Check the ID with the responsible clinician.")
    if has_access(db, user, patient.id, write=data.capability == "clinical:write"):
        raise HTTPException(409, "You already have this level of access.")
    existing = db.scalar(
        select(ClinicalGrant).where(
            ClinicalGrant.patient_id == patient.id,
            ClinicalGrant.subject_id == user.id,
            ClinicalGrant.capability == data.capability,
            ClinicalGrant.state == "pending",
        )
    )
    if existing:
        raise HTTPException(409, "You already have a pending request for this access.")
    gid = str(uuid4())
    row = ClinicalGrant(
        id=gid,
        patient_id=patient.id,
        subject_id=user.id,
        requester_id=user.id,
        capability=data.capability,
        state="pending",
        version=1,
        payload=encrypt({"reason": data.reason, "history": []}, f"grant:{gid}"),
    )
    db.add(row)
    record_audit(db, request, user, "grant.request", gid)
    db.flush()
    output = result(db, user, row)
    db.commit()
    return output


def review(db, user, request, grant_id: UUID, data):
    require(user, "grants:approve")
    row = locked(db, user, grant_id, data.expectedVersion)
    independent(user, row)
    if row.state != "pending":
        raise HTTPException(409, "This request has already been decided.")
    if data.decision == "approve":
        subject = db.get(User, row.subject_id)
        patient = db.get(Patient, row.patient_id)
        if (
            not subject.active
            or not subject.credentials_ready
            or subject.password_reset_required
            or row.capability not in subject.capabilities
            or patient.status != "active"
        ):
            raise HTTPException(409, "The account or patient is not eligible for this access.")
    row.state = "approved" if data.decision == "approve" else "denied"
    row.approver_id = user.id
    row.reviewed_at = now()
    return save(db, request, user, row, data.decision, data.comment)


def revoke(db, user, request, grant_id: UUID, data):
    require(user, "grants:approve")
    row = locked(db, user, grant_id, data.expectedVersion)
    independent(user, row)
    if row.state != "approved":
        raise HTTPException(409, "Only approved grants can be revoked.")
    row.state = "revoked"
    return save(db, request, user, row, "revoke", data.reason)


def cancel(db, user, request, grant_id: UUID, data):
    row = locked(db, user, grant_id, data.expectedVersion)
    if row.subject_id != user.id:
        raise HTTPException(404, "Request unavailable.")
    if row.state != "pending":
        raise HTTPException(409, "Only pending requests can be cancelled.")
    row.state = "cancelled"
    return save(db, request, user, row, "cancel", "Cancelled by requester")
