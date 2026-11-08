"""Explicit clinician-confirmed ratings; values are never inferred from prose."""
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select

from ..adapters.crypto import decrypt, encrypt
from ..db.models import ClinicalNote, ConfirmedRating, now
from .audit import record_audit
from .authorization import has_access, require, scoped_patient
from .sessions import content_of
from .summaries import current_note, snapshot as note_snapshot


def rows(db, pid):
    return db.scalars(
        select(ConfirmedRating)
        .where(ConfirmedRating.patient_id == pid)
        .order_by(ConfirmedRating.created_at, ConfirmedRating.id)
    ).all()


def rating_output(db, row):
    payload = decrypt(row.payload, f"rating:{row.patient_id}:{row.id}")
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
            decrypt(row.withdrawal, f"rating-withdrawal:{row.patient_id}:{row.id}")["reason"]
            if row.withdrawal
            else None
        ),
    }


def list_ratings(db, user, request, patient_id):
    patient = scoped_patient(db, user, patient_id, clinical=True)
    can_write = (
        patient.status == "active"
        and has_access(db, user, patient.id, write=True)
        and "indicators:write" in user.capabilities
    )
    result = {
        "items": [rating_output(db, r) for r in rows(db, patient.id)],
        "allowedActions": ["create", "withdraw"] if can_write else [],
    }
    record_audit(db, request, user, "rating.list", patient.id)
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
    record_audit(db, request, user, "rating.sources", patient.id)
    db.commit()
    return {"items": items}


def create_rating(db, user, request, patient_id, data):
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
        value = rating_output(db, old)
        if (
            old.state == "confirmed"
            and value["sourceId"] == note.id
            and value["scaleName"].casefold() == data.scaleName.casefold()
        ):
            raise HTTPException(
                409,
                "This source already has a confirmed rating for that scale. Withdraw the incorrect rating before recording its replacement.",
            )
    rid = str(uuid4())
    content = content_of(note)
    payload = {
        "sourceId": note.id,
        "sourceVersion": note.version,
        "scaleName": data.scaleName,
        "value": data.value,
        "higherMeans": data.higherMeans,
        "eventDate": note.event_date.isoformat() if note.event_date else None,
        "dateStatus": content.get("dateStatus", "known" if note.event_date else "unknown"),
        "confirmedBy": user.display_name,
        "confirmedById": user.id,
        "href": f"/patients/{patient.id}/sessions/{note.id}",
    }
    row = ConfirmedRating(
        id=rid,
        patient_id=patient.id,
        created_by=user.id,
        state="confirmed",
        version=1,
        payload=encrypt(payload, f"rating:{patient.id}:{rid}"),
    )
    db.add(row)
    record_audit(db, request, user, "rating.confirm", rid)
    db.flush()
    result = rating_output(db, row)
    db.commit()
    return result


def withdraw(db, user, request, patient_id, rating_id, data):
    require(user, "indicators:write")
    patient = scoped_patient(db, user, patient_id, clinical=True, lock=True)
    if patient.status != "active":
        raise HTTPException(409, "Archived patients are read-only.")
    row = db.scalar(
        select(ConfirmedRating).where(
            ConfirmedRating.id == str(rating_id),
            ConfirmedRating.patient_id == patient.id,
        )
    )
    if row is None:
        raise HTTPException(404, "Rating unavailable.")
    if row.version != data.expectedVersion or row.state != "confirmed":
        raise HTTPException(409, "This rating changed. Refresh before withdrawing it.")
    row.state = "withdrawn"
    row.version += 1
    row.withdrawal = encrypt(
        {"reason": data.reason, "actorId": user.id, "at": now().isoformat()},
        f"rating-withdrawal:{patient.id}:{row.id}",
    )
    record_audit(db, request, user, "rating.withdraw", row.id)
    db.flush()
    result = rating_output(db, row)
    db.commit()
    return result
