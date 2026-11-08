from datetime import date
from datetime import datetime
from typing import Literal
from uuid import UUID
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from ..adapters.crypto import decrypt
from ..adapters.crypto import encrypt
from ..core.config import get_settings
from ..db.models import AISummary
from ..db.models import ClinicalNote
from ..db.models import FollowUp
from ..db.models import Patient
from ..db.models import PatientAccess
from ..db.models import PatientEvent
from ..db.models import User
from .audit import record_audit
from .authorization import access_ids
from .authorization import has_access
from .authorization import require
from .authorization import scoped_patient
from .summaries import sources_current


class PatientOutput(BaseModel):
    id: str
    displayName: str
    dateOfBirth: date | None
    status: Literal["active", "archived", "deleting"]
    assignment: str
    assignedPractitionerIds: list[str]
    version: int
    allowedActions: list[str]


class PatientList(BaseModel):
    items: list[PatientOutput]


def clinic_today():
    return datetime.now(ZoneInfo(get_settings().clinic_timezone)).date()


def event(db, user, patient, title, kind="patient"):
    db.add(
        PatientEvent(
            patient_id=patient.id,
            actor_id=user.id,
            kind=kind,
            title=title,
            event_date=clinic_today(),
            version=patient.version,
        )
    )


def task_output(task):
    payload = decrypt(task.payload, f"follow-up:{task.patient_id}:{task.id}")
    return {"id": task.id, **payload, "state": task.state, "source": "Manual"}


def serialize(db, user, patient) -> PatientOutput:
    profile = decrypt(patient.profile, f"patient:{patient.id}")
    scoped = has_access(db, user, patient.id)
    actions = []
    if scoped and "clinical:read" in user.capabilities:
        actions.append("clinical:read")
    if (scoped and has_access(db, user, patient.id, write=True) and "clinical:write" in user.capabilities) or "users:manage" in user.capabilities:
        actions.extend(["archive", "edit"])
    if scoped and "patients:delete" in user.capabilities and "users:manage" in user.capabilities:
        actions.append("delete")
    practitioner = db.get(User, patient.primary_practitioner_id)
    return PatientOutput(
        id=patient.id,
        displayName=profile["displayName"],
        dateOfBirth=profile["dateOfBirth"],
        status=patient.status,
        version=patient.version,
        assignment=practitioner.display_name,
        assignedPractitionerIds=[patient.primary_practitioner_id],
        allowedActions=actions,
    )


def profile_write(db, user, patient_id, expected):
    patient = scoped_patient(db, user, patient_id, lock=True)
    if "users:manage" not in user.capabilities:
        require(user, "clinical:write")
    if patient.version != expected:
        raise HTTPException(409, "A newer patient version exists. Refresh and try again.")
    return patient


def set_status(db, user, request, patient_id, data, status):
    patient = profile_write(db, user, patient_id, data.expectedVersion)
    if patient.status != status:
        patient.status = status
        db.flush()
        event(db, user, patient, "Patient archived" if status == "archived" else "Patient reactivated")
        record_audit(db, request, user, "patient.archive" if status == "archived" else "patient.reactivate", patient.id)
    result = serialize(db, user, patient)
    db.commit()
    return result


def archive_patient(db, user, request, patient_id, data):
    return set_status(db, user, request, patient_id, data, "archived")


def reactivate_patient(db, user, request, patient_id, data):
    return set_status(db, user, request, patient_id, data, "active")


def list_patients(db, user, request, status: Literal["active", "archived"] = "active", q: str = ""):
    require(user, "patients:read")
    statement = select(Patient).where(Patient.status == status).order_by(Patient.created_at.desc(), Patient.id)
    if "users:manage" not in user.capabilities:
        statement = statement.where(Patient.id.in_(access_ids(user)))
    items = [serialize(db, user, patient) for patient in db.scalars(statement)]
    search = q.strip().casefold()
    if search:
        # Only already-authorized rows are decrypted; no plaintext search index.
        items = [p for p in items if search in p.displayName.casefold() or search in p.id.casefold()]
    record_audit(db, request, user, "patient.list", None)
    db.commit()
    return {"items": items}


def create_patient(db, user, request, data):
    require(user, "patients:create")
    practitioner_id = str(data.initialPractitionerId) if data.initialPractitionerId else user.id
    if "users:manage" not in user.capabilities:
        require(user, "clinical:write")
        if practitioner_id != user.id:
            raise HTTPException(403, "You can only create patients linked to your own account.")
    practitioner = db.get(User, practitioner_id)
    if practitioner is None or not practitioner.active or "clinical:write" not in practitioner.capabilities:
        raise HTTPException(422, "Choose an active practitioner.")
    patient_id = str(uuid4())
    profile = {
        "displayName": data.displayName,
        "dateOfBirth": data.dateOfBirth.isoformat() if data.dateOfBirth else None,
    }
    patient = Patient(
        id=patient_id,
        profile=encrypt(profile, f"patient:{patient_id}"),
        created_by=user.id,
        primary_practitioner_id=practitioner_id,
    )
    db.add(patient)
    db.flush()
    db.add(PatientAccess(patient_id=patient.id, user_id=practitioner_id))
    event(db, user, patient, "Patient profile created")
    record_audit(db, request, user, "patient.create", patient.id)
    result = serialize(db, user, patient)
    db.commit()
    return result


def get_patient(db, user, request, patient_id: UUID):
    patient = scoped_patient(db, user, patient_id)
    result = serialize(db, user, patient)
    record_audit(db, request, user, "patient.read", patient.id)
    db.commit()
    return result


def update_patient(db, user, request, patient_id: UUID, data):
    patient = profile_write(db, user, patient_id, data.expectedVersion)
    changes = data.model_dump(mode="json", exclude_unset=True, exclude={"expectedVersion"})
    if not changes:
        raise HTTPException(422, "Supply a name or date of birth to update.")
    profile = decrypt(patient.profile, f"patient:{patient.id}")
    profile.update(changes)
    patient.profile = encrypt(profile, f"patient:{patient.id}")
    db.flush()  # SQLAlchemy increments version and rejects conflicting concurrent saves.
    event(db, user, patient, "Patient profile updated")
    record_audit(db, request, user, "patient.update", patient.id)
    result = serialize(db, user, patient)
    db.commit()
    return result


def timeline(db, user, request, patient_id: UUID):
    patient = scoped_patient(db, user, patient_id, clinical=True)
    rows = db.execute(
        select(PatientEvent, User.display_name)
        .join(User, User.id == PatientEvent.actor_id)
        .where(PatientEvent.patient_id == patient.id)
        .order_by(PatientEvent.created_at.desc())
    ).all()
    items = [
        {
            "id": e.id,
            "type": e.kind,
            "title": e.title,
            "eventDate": e.event_date,
            "createdAt": e.created_at,
            "author": author,
            "version": e.version,
        }
        for e, author in rows
    ]
    notes = db.execute(
        select(ClinicalNote, User.display_name)
        .join(User, User.id == ClinicalNote.author_id)
        .where(ClinicalNote.patient_id == patient.id)
        .order_by(ClinicalNote.created_at.desc())
    ).all()
    for note, author in notes:
        note_content = decrypt(note.payload, f"session:{patient.id}:{note.id}")
        items.append(
            {
                "id": note.id,
                "type": "amendment" if note.parent_id else "session",
                "title": (
                    "Session amendment"
                    if note.parent_id
                    else "Imported historical session"
                    if note_content.get("source")
                    else "Session note"
                ),
                "dateStatus": note_content.get("dateStatus", "known" if note.event_date else "unknown"),
                "eventDate": note.event_date,
                "createdAt": note.created_at,
                "author": author,
                "version": note.version,
                "status": note.state,
                "href": f"/patients/{patient.id}/sessions/{note.id}",
            }
        )
    for summary in db.scalars(select(AISummary).where(AISummary.patient_id == patient.id)):
        payload = decrypt(summary.payload, f"summary:{patient.id}:{summary.id}")
        items.append(
            {
                "id": summary.id,
                "type": "summary",
                "title": "AI summary",
                "eventDate": None,
                "createdAt": summary.created_at,
                "author": db.get(User, summary.created_by).display_name,
                "version": summary.version,
                "status": payload["reviewState"],
                "freshness": "current" if sources_current(db, patient.id, payload["sources"]) else "stale",
                "href": f"/patients/{patient.id}/summaries/{summary.id}",
            }
        )
    record_audit(db, request, user, "timeline.read", patient.id)
    db.commit()
    return {"items": items}


def list_tasks(db, user, request, patient_id: UUID):
    patient = scoped_patient(db, user, patient_id, clinical=True)
    items = [
        task_output(t)
        for t in db.scalars(
            select(FollowUp)
            .where(FollowUp.patient_id == patient.id)
            .order_by(FollowUp.created_at.desc())
        )
    ]
    record_audit(db, request, user, "follow_up.list", patient.id)
    db.commit()
    return {"items": items}


def create_task(db, user, request, patient_id: UUID, data):
    patient = scoped_patient(db, user, patient_id, write=True, lock=True)
    if patient.status != "active":
        raise HTTPException(409, "Reactivate the patient before adding follow-ups.")
    task_id = str(uuid4())
    task = FollowUp(
        id=task_id,
        patient_id=patient.id,
        created_by=user.id,
        payload=encrypt(data.model_dump(mode="json"), f"follow-up:{patient.id}:{task_id}"),
    )
    db.add(task)
    db.flush()
    event(db, user, patient, "Follow-up created", "follow_up")
    record_audit(db, request, user, "follow_up.create", task.id)
    result = task_output(task)
    db.commit()
    return result


def update_task(db, user, request, patient_id: UUID, task_id: UUID, data):
    patient = scoped_patient(db, user, patient_id, write=True, lock=True)
    task = db.scalar(
        select(FollowUp).where(FollowUp.id == str(task_id), FollowUp.patient_id == patient.id)
    )
    if task is None:
        raise HTTPException(404, "Follow-up unavailable.")
    if task.state != "open" and task.state != data.state:
        raise HTTPException(409, "This follow-up is already closed.")
    if task.state != data.state:
        task.state = data.state
        event(db, user, patient, "Follow-up " + data.state, "follow_up")
        record_audit(db, request, user, "follow_up." + data.state, task.id)
    result = task_output(task)
    db.commit()
    return result
