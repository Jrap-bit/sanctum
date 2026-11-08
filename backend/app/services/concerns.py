"""Explicit clinician-confirmed concerns; values are never inferred from prose."""
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select

from ..adapters.crypto import decrypt, encrypt
from ..db.models import ClinicalNote, ConfirmedConcern, now
from .audit import record_audit
from .authorization import has_access, require, scoped_patient
from .sessions import content_of
from .summaries import current_note, snapshot as note_snapshot


def rows(db, pid):
    return db.scalars(
        select(ConfirmedConcern)
        .where(ConfirmedConcern.patient_id == pid)
        .order_by(ConfirmedConcern.created_at, ConfirmedConcern.id)
    ).all()


def concern_output(db, row):
    payload = decrypt(row.payload, f"concern:{row.patient_id}:{row.id}")
    note = db.get(ClinicalNote, payload["sourceId"])
    current = bool(
        note
        and note.patient_id == row.patient_id
        and current_note(db, note)
        and note.version == payload["sourceVersion"]
    )
    return {
        "id": row.id,
        "version": row.version,
        "state": row.state,
        "freshness": "current" if current else "stale",
        **payload,
        "confirmedAt": row.created_at.isoformat(),
        "withdrawalReason": (
            decrypt(row.withdrawal, f"concern-withdrawal:{row.patient_id}:{row.id}")["reason"]
            if row.withdrawal
            else None
        ),
    }


def session_snapshot(db, patient_id):
    notes = db.scalars(
        select(ClinicalNote)
        .where(ClinicalNote.patient_id == patient_id, ClinicalNote.state == "finalized")
        .order_by(ClinicalNote.id)
    ).all()
    return [
        {
            "id": n.id,
            "version": n.version,
            "eventDate": n.event_date.isoformat() if n.event_date else None,
            "dateStatus": content_of(n).get("dateStatus", "known" if n.event_date else "unknown"),
            "href": f"/patients/{patient_id}/sessions/{n.id}",
        }
        for n in notes
        if current_note(db, n)
    ]


def list_concerns(db, user, request, patient_id):
    patient = scoped_patient(db, user, patient_id, clinical=True)
    can_write = (
        patient.status == "active"
        and has_access(db, user, patient.id, write=True)
        and "indicators:write" in user.capabilities
    )
    result = {
        "items": [concern_output(db, r) for r in rows(db, patient.id)],
        "allowedActions": ["create", "withdraw"] if can_write else [],
    }
    record_audit(db, request, user, "concern.list", patient.id)
    db.commit()
    return result


def sources(db, user, request, patient_id):
    patient = scoped_patient(db, user, patient_id, clinical=True)
    notes = db.scalars(
        select(ClinicalNote)
        .where(ClinicalNote.patient_id == patient.id, ClinicalNote.state == "finalized")
        .order_by(ClinicalNote.created_at)
    ).all()
    items = [{k: v for k, v in note_snapshot(n).items() if k != "text"} for n in notes if current_note(db, n)]
    record_audit(db, request, user, "concern.sources", patient.id)
    db.commit()
    return {"items": items}


def create_concern(db, user, request, patient_id, data):
    require(user, "indicators:write")
    patient = scoped_patient(db, user, patient_id, clinical=True, lock=True)
    if patient.status != "active":
        raise HTTPException(409, "Archived patients are read-only.")
    note = db.scalar(
        select(ClinicalNote).where(
            ClinicalNote.id == str(data.sourceId),
            ClinicalNote.patient_id == patient.id,
        )
    )
    if not current_note(db, note) or note.version != data.sourceVersion:
        raise HTTPException(409, "Select a current finalized source note.")
    for old in rows(db, patient.id):
        value = concern_output(db, old)
        if (
            old.state == "confirmed"
            and value["sourceId"] == note.id
            and value["concernCode"] == data.concernCode
        ):
            raise HTTPException(
                409,
                "This source already has a confirmed concern for that category. Withdraw the incorrect concern before recording its replacement.",
            )
    rid = str(uuid4())
    content = content_of(note)
    if (
        not data.quotation.strip()
        or " ".join(data.quotation.split()) not in " ".join(note_snapshot(note)["text"].split())
    ):
        raise HTTPException(422, "Copy a supporting quotation from the selected source note.")
    payload = {
        "sourceId": note.id,
        "sourceVersion": note.version,
        "concernCode": data.concernCode,
        "assertion": data.assertion,
        "temporality": data.temporality,
        "subject": data.subject,
        "quotation": data.quotation,
        "eventDate": note.event_date.isoformat() if note.event_date else None,
        "dateStatus": content.get("dateStatus", "known" if note.event_date else "unknown"),
        "confirmedBy": user.display_name,
        "confirmedById": user.id,
        "href": f"/patients/{patient.id}/sessions/{note.id}",
    }
    row = ConfirmedConcern(
        id=rid,
        patient_id=patient.id,
        created_by=user.id,
        state="confirmed",
        version=1,
        payload=encrypt(payload, f"concern:{patient.id}:{rid}"),
    )
    db.add(row)
    record_audit(db, request, user, "concern.confirm", rid)
    db.flush()
    result = concern_output(db, row)
    db.commit()
    return result


def withdraw(db, user, request, patient_id, concern_id, data):
    require(user, "indicators:write")
    patient = scoped_patient(db, user, patient_id, clinical=True, lock=True)
    if patient.status != "active":
        raise HTTPException(409, "Archived patients are read-only.")
    row = db.scalar(
        select(ConfirmedConcern).where(
            ConfirmedConcern.id == str(concern_id),
            ConfirmedConcern.patient_id == patient.id,
        )
    )
    if row is None:
        raise HTTPException(404, "Concern unavailable.")
    if row.version != data.expectedVersion or row.state != "confirmed":
        raise HTTPException(409, "This concern changed. Refresh before withdrawing it.")
    row.state = "withdrawn"
    row.version += 1
    row.withdrawal = encrypt(
        {"reason": data.reason, "actorId": user.id, "at": now().isoformat()},
        f"concern-withdrawal:{patient.id}:{row.id}",
    )
    record_audit(db, request, user, "concern.withdraw", row.id)
    db.flush()
    result = concern_output(db, row)
    db.commit()
    return result
