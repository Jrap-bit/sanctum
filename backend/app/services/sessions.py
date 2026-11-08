from datetime import date
from datetime import datetime
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from sqlalchemy import select

from ..adapters.crypto import decrypt
from ..adapters.crypto import encrypt
from ..db.models import ClinicalNote
from ..db.models import User
from ..db.models import now
from .audit import record_audit
from .authorization import has_access
from .authorization import scoped_patient


SECTIONS = ("concerns", "observations", "interventions", "medicationReported")


class NoteField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=4000)
    assertion: Literal["present", "denied", "possible", "unknown"] = "unknown"
    temporality: Literal["current", "historical", "unknown"] = "unknown"


class SessionOutput(BaseModel):
    id: str
    patientId: str
    eventDate: date | None
    state: Literal["draft", "finalized"]
    version: int
    text: str
    concerns: list[NoteField]
    observations: list[NoteField]
    interventions: list[NoteField]
    medicationReported: list[NoteField]
    author: str
    updatedAt: datetime
    source: dict | None = None
    dateStatus: Literal["known", "approximate", "unknown"] = "unknown"
    amendmentReason: str | None = None
    versions: list["SessionOutput"] = Field(default_factory=list)
    allowedActions: list[str]


def content_of(note):
    return decrypt(note.payload, f"session:{note.patient_id}:{note.id}")


def scoped_note(db, patient, note_id):
    note = db.scalar(
        select(ClinicalNote).where(
            ClinicalNote.id == str(note_id),
            ClinicalNote.patient_id == patient.id,
        )
    )
    if note is None:
        raise HTTPException(404, "Session unavailable.")
    return note


def output(db, user, patient, note, *, history=True):
    content = content_of(note)
    content.setdefault("dateStatus", "known" if note.event_date else "unknown")
    actions = []
    if (
        patient.status == "active"
        and has_access(db, user, patient.id, write=True)
        and "clinical:write" in user.capabilities
    ):
        if note.state == "draft" and note.author_id == user.id:
            actions = ["edit", "finalize"]
        elif note.state == "finalized":
            child = db.scalar(select(ClinicalNote.id).where(ClinicalNote.parent_id == note.id))
            if child is None:
                actions = ["amend"]
    result = SessionOutput(
        id=note.id,
        patientId=note.patient_id,
        eventDate=note.event_date,
        state=note.state,
        version=note.version,
        author=db.get(User, note.author_id).display_name,
        updatedAt=note.updated_at,
        allowedActions=actions,
        **content,
    )
    if history:
        parent_id = note.parent_id
        while parent_id:
            parent = scoped_note(db, patient, parent_id)
            previous = output(db, user, patient, parent, history=False)
            previous.allowedActions = []
            result.versions.append(previous)
            parent_id = parent.parent_id
    return result


def editable_patient(db, user, patient_id):
    # Lock the patient to serialize note mutations with archive and amendment actions.
    patient = scoped_patient(db, user, patient_id, write=True, lock=True)
    if patient.status != "active":
        raise HTTPException(409, "Reactivate this patient before changing session notes.")
    return patient


def check_version(note, expected):
    if note.version != expected:
        raise HTTPException(409, "A newer session version exists. Compare it before saving again.")


def check_draft_author(note, user):
    if note.state != "draft":
        raise HTTPException(409, "Finalized notes are read-only. Create an amendment instead.")
    if note.author_id != user.id:
        raise HTTPException(403, "Only the draft's author may edit or finalize it.")


def create_session(db, user, request, patient_id, data):
    patient = editable_patient(db, user, patient_id)
    note_id = str(uuid4())
    content = {"text": "", **{section: [] for section in SECTIONS}, "amendmentReason": None}
    note = ClinicalNote(
        id=note_id,
        patient_id=patient.id,
        author_id=user.id,
        event_date=data.eventDate,
        payload=encrypt(content, f"session:{patient.id}:{note_id}"),
        version=1,
    )
    db.add(note)
    db.flush()
    record_audit(db, request, user, "session.create", note.id)
    result = output(db, user, patient, note)
    db.commit()
    return result


def get_session(db, user, request, patient_id, session_id):
    patient = scoped_patient(db, user, patient_id, clinical=True)
    note = scoped_note(db, patient, session_id)
    result = output(db, user, patient, note)
    record_audit(db, request, user, "session.read", note.id)
    db.commit()
    return result


def save_draft(db, user, request, patient_id, session_id, data):
    patient = editable_patient(db, user, patient_id)
    note = scoped_note(db, patient, session_id)
    check_version(note, data.expectedVersion)
    check_draft_author(note, user)
    content = data.model_dump(mode="json", exclude={"expectedVersion", "eventDate"})
    # Amendment reasons are established once, not silently editable through draft saves.
    old_content = content_of(note)
    content["amendmentReason"] = old_content["amendmentReason"]
    if old_content.get("source"):
        content["source"] = old_content["source"]
    content["dateStatus"] = (
        old_content.get("dateStatus", "known" if note.event_date else "unknown")
        if data.eventDate == note.event_date
        else ("known" if data.eventDate else "unknown")
    )
    note.payload = encrypt(content, f"session:{patient.id}:{note.id}")
    note.event_date = data.eventDate
    note.version += 1
    note.updated_at = now()
    db.flush()
    record_audit(db, request, user, "session.save", note.id)
    result = output(db, user, patient, note)
    db.commit()
    return result


def finalize_session(db, user, request, patient_id, session_id, data):
    patient = editable_patient(db, user, patient_id)
    note = scoped_note(db, patient, session_id)
    check_version(note, data.expectedVersion)
    check_draft_author(note, user)
    content = content_of(note)
    if not content["text"].strip() and not any(
        item["text"].strip() for section in SECTIONS for item in content[section]
    ):
        raise HTTPException(422, "Add a note or structured detail before finalizing.")
    note.state = "finalized"
    note.finalized_at = note.updated_at = now()
    note.version += 1
    db.flush()
    record_audit(db, request, user, "session.finalize", note.id)
    result = output(db, user, patient, note)
    db.commit()
    return result


def create_amendment(db, user, request, patient_id, session_id, data):
    patient = editable_patient(db, user, patient_id)
    original = scoped_note(db, patient, session_id)
    check_version(original, data.expectedVersion)
    if original.state != "finalized":
        raise HTTPException(409, "Only finalized notes can be amended.")
    if db.scalar(select(ClinicalNote.id).where(ClinicalNote.parent_id == original.id)):
        raise HTTPException(409, "An amendment already exists. Open it from the patient timeline.")
    note_id = str(uuid4())
    content = content_of(original)
    content["amendmentReason"] = data.reason
    amendment = ClinicalNote(
        id=note_id,
        patient_id=patient.id,
        author_id=user.id,
        parent_id=original.id,
        event_date=original.event_date,
        version=original.version + 1,
        payload=encrypt(content, f"session:{patient.id}:{note_id}"),
    )
    db.add(amendment)
    db.flush()
    record_audit(db, request, user, "session.amendment_create", amendment.id)
    result = output(db, user, patient, amendment)
    db.commit()
    return result
