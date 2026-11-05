"""Patient profiles and their overview. All clinical access is checked on the server."""
from datetime import date, datetime
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from .auth import CurrentUser, Db
from .config import get_settings
from .crypto import decrypt, encrypt
from .models import AuditEvent, ClinicalNote, FollowUp, Patient, PatientAccess, PatientEvent, User

router = APIRouter(prefix="/api/v1", tags=["Patients"])


def clinic_today():
    return datetime.now(ZoneInfo(get_settings().clinic_timezone)).date()


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileFields(Input):
    displayName: str = Field(min_length=1, max_length=160)
    dateOfBirth: date | None = None

    @field_validator("displayName")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("A patient name is required.")
        return value.strip()

    @field_validator("dateOfBirth")
    @classmethod
    def valid_birth_date(cls, value):
        if value and value > clinic_today():
            raise ValueError("Date of birth cannot be in the future.")
        return value


class CreatePatient(ProfileFields):
    initialPractitionerId: UUID | None = None


class UpdatePatient(Input):
    expectedVersion: int = Field(ge=1)
    displayName: str | None = Field(default=None, min_length=1, max_length=160)
    dateOfBirth: date | None = None

    @field_validator("displayName")
    @classmethod
    def clean_name(cls, value):
        if value is None or not value.strip():
            raise ValueError("A patient name is required.")
        return value.strip()

    @field_validator("dateOfBirth")
    @classmethod
    def valid_birth_date(cls, value):
        return ProfileFields.valid_birth_date(value)


class VersionInput(Input):
    expectedVersion: int = Field(ge=1)


class PatientOutput(BaseModel):
    id: str
    displayName: str
    dateOfBirth: date | None
    status: Literal["active", "archived"]
    assignment: str
    assignedPractitionerIds: list[str]
    version: int
    allowedActions: list[str]


class PatientList(BaseModel):
    items: list[PatientOutput]


class TaskInput(Input):
    title: str = Field(min_length=1, max_length=240)
    details: str = Field(default="", max_length=4000)
    dueDate: date | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value):
        if not value.strip():
            raise ValueError("A follow-up title is required.")
        return value.strip()


class TaskUpdate(Input):
    state: Literal["completed", "cancelled"]


def require(user, capability):
    if capability not in user.capabilities:
        raise HTTPException(403, "This action is outside your permissions.")


def has_access(db, user, patient_id):
    return db.get(PatientAccess, (patient_id, user.id)) is not None


def scoped_patient(db, user, patient_id, *, clinical=False, write=False, lock=False):
    require(user, "clinical:write" if write else "clinical:read" if clinical else "patients:read")
    statement = select(Patient).where(Patient.id == str(patient_id))
    # Profile administrators get identity access only, never implicit clinical access.
    if clinical or write or "users:manage" not in user.capabilities:
        statement = statement.where(Patient.id.in_(select(PatientAccess.patient_id).where(PatientAccess.user_id == user.id)))
    if lock:
        statement = statement.with_for_update()
    patient = db.scalar(statement)
    if patient is None:
        raise HTTPException(404, "Patient unavailable.")
    return patient


def record_audit(db, request, user, action, target):
    db.add(AuditEvent(actor_id=user.id, action=action, target_id=target,
                      outcome="success", request_id=request.state.request_id))


def event(db, user, patient, title, kind="patient"):
    db.add(PatientEvent(patient_id=patient.id, actor_id=user.id, kind=kind,
                        title=title, event_date=clinic_today(), version=patient.version))


def serialize(db, user, patient):
    profile = decrypt(patient.profile, f"patient:{patient.id}")
    scoped = has_access(db, user, patient.id)
    actions = []
    if scoped and "clinical:read" in user.capabilities:
        actions.append("clinical:read")
    if (scoped and "clinical:write" in user.capabilities) or "users:manage" in user.capabilities:
        actions.extend(["archive", "edit"])
    practitioner = db.get(User, patient.primary_practitioner_id)
    return PatientOutput(id=patient.id, displayName=profile["displayName"], dateOfBirth=profile["dateOfBirth"],
                         status=patient.status, version=patient.version, assignment=practitioner.display_name,
                         assignedPractitionerIds=[patient.primary_practitioner_id], allowedActions=actions)


@router.get("/patients", response_model=PatientList)
def list_patients(user: CurrentUser, db: Db, request: Request,
                  status: Literal["active", "archived"] = "active", q: str = ""):
    require(user, "patients:read")
    statement = select(Patient).where(Patient.status == status).order_by(Patient.created_at.desc(), Patient.id)
    if "users:manage" not in user.capabilities:
        statement = statement.where(Patient.id.in_(select(PatientAccess.patient_id).where(PatientAccess.user_id == user.id)))
    items = [serialize(db, user, patient) for patient in db.scalars(statement)]
    search = q.strip().casefold()
    if search:
        # Only already-authorized rows are decrypted; no plaintext search index.
        items = [p for p in items if search in p.displayName.casefold() or search in p.id.casefold()]
    record_audit(db, request, user, "patient.list", None)
    db.commit()
    return {"items": items}


@router.post("/patients", response_model=PatientOutput, status_code=201)
def create_patient(data: CreatePatient, user: CurrentUser, db: Db, request: Request):
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
    profile = {"displayName": data.displayName, "dateOfBirth": data.dateOfBirth.isoformat() if data.dateOfBirth else None}
    patient = Patient(id=patient_id, profile=encrypt(profile, f"patient:{patient_id}"),
                      created_by=user.id, primary_practitioner_id=practitioner_id)
    db.add(patient)
    db.flush()
    db.add(PatientAccess(patient_id=patient.id, user_id=practitioner_id))
    event(db, user, patient, "Patient profile created")
    record_audit(db, request, user, "patient.create", patient.id)
    result = serialize(db, user, patient)
    db.commit()
    return result


@router.get("/patients/{patient_id}", response_model=PatientOutput)
def get_patient(patient_id: UUID, user: CurrentUser, db: Db, request: Request):
    patient = scoped_patient(db, user, patient_id)
    result = serialize(db, user, patient)
    record_audit(db, request, user, "patient.read", patient.id)
    db.commit()
    return result


def profile_write(db, user, patient_id, expected):
    patient = scoped_patient(db, user, patient_id, lock=True)
    if "users:manage" not in user.capabilities:
        require(user, "clinical:write")
    if patient.version != expected:
        raise HTTPException(409, "A newer patient version exists. Refresh and try again.")
    return patient


@router.patch("/patients/{patient_id}", response_model=PatientOutput)
def update_patient(patient_id: UUID, data: UpdatePatient, user: CurrentUser, db: Db, request: Request):
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


def set_status(patient_id, data, user, db, request, status):
    patient = profile_write(db, user, patient_id, data.expectedVersion)
    if patient.status != status:
        patient.status = status
        db.flush()
        event(db, user, patient, "Patient archived" if status == "archived" else "Patient reactivated")
        record_audit(db, request, user, "patient.archive" if status == "archived" else "patient.reactivate", patient.id)
    result = serialize(db, user, patient)
    db.commit()
    return result


@router.post("/patients/{patient_id}/archive", response_model=PatientOutput)
def archive_patient(patient_id: UUID, data: VersionInput, user: CurrentUser, db: Db, request: Request):
    return set_status(patient_id, data, user, db, request, "archived")


@router.post("/patients/{patient_id}/reactivate", response_model=PatientOutput)
def reactivate_patient(patient_id: UUID, data: VersionInput, user: CurrentUser, db: Db, request: Request):
    return set_status(patient_id, data, user, db, request, "active")


@router.get("/patients/{patient_id}/timeline")
def timeline(patient_id: UUID, user: CurrentUser, db: Db, request: Request):
    patient = scoped_patient(db, user, patient_id, clinical=True)
    rows = db.execute(select(PatientEvent, User.display_name).join(User, User.id == PatientEvent.actor_id)
                      .where(PatientEvent.patient_id == patient.id).order_by(PatientEvent.created_at.desc())).all()
    items = [{"id": e.id, "type": e.kind, "title": e.title, "eventDate": e.event_date,
              "createdAt": e.created_at, "author": author, "version": e.version} for e, author in rows]
    notes = db.execute(select(ClinicalNote, User.display_name).join(User, User.id == ClinicalNote.author_id)
                       .where(ClinicalNote.patient_id == patient.id).order_by(ClinicalNote.created_at.desc())).all()
    for note, author in notes:
        items.append({"id": note.id, "type": "amendment" if note.parent_id else "session",
                      "title": "Session amendment" if note.parent_id else "Session note",
                      "eventDate": note.event_date, "createdAt": note.created_at,
                      "author": author, "version": note.version, "status": note.state,
                      "href": f"/patients/{patient.id}/sessions/{note.id}"})
    record_audit(db, request, user, "timeline.read", patient.id)
    db.commit()
    return {"items": items}


def task_output(task):
    payload = decrypt(task.payload, f"follow-up:{task.patient_id}:{task.id}")
    return {"id": task.id, **payload, "state": task.state, "source": "Manual"}


@router.get("/patients/{patient_id}/follow-ups")
def list_tasks(patient_id: UUID, user: CurrentUser, db: Db, request: Request):
    patient = scoped_patient(db, user, patient_id, clinical=True)
    items = [task_output(t) for t in db.scalars(select(FollowUp).where(FollowUp.patient_id == patient.id)
                                               .order_by(FollowUp.created_at.desc()))]
    record_audit(db, request, user, "follow_up.list", patient.id)
    db.commit()
    return {"items": items}


@router.post("/patients/{patient_id}/follow-ups", status_code=201)
def create_task(patient_id: UUID, data: TaskInput, user: CurrentUser, db: Db, request: Request):
    patient = scoped_patient(db, user, patient_id, write=True, lock=True)
    if patient.status != "active":
        raise HTTPException(409, "Reactivate the patient before adding follow-ups.")
    task_id = str(uuid4())
    task = FollowUp(id=task_id, patient_id=patient.id, created_by=user.id,
                    payload=encrypt(data.model_dump(mode="json"), f"follow-up:{patient.id}:{task_id}"))
    db.add(task)
    db.flush()
    event(db, user, patient, "Follow-up created", "follow_up")
    record_audit(db, request, user, "follow_up.create", task.id)
    result = task_output(task)
    db.commit()
    return result


@router.patch("/patients/{patient_id}/follow-ups/{task_id}")
def update_task(patient_id: UUID, task_id: UUID, data: TaskUpdate, user: CurrentUser, db: Db, request: Request):
    patient = scoped_patient(db, user, patient_id, write=True, lock=True)
    task = db.scalar(select(FollowUp).where(FollowUp.id == str(task_id), FollowUp.patient_id == patient.id))
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
