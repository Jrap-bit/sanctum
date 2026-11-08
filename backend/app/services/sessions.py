from fastapi import HTTPException
from sqlalchemy import select

from ..adapters.crypto import decrypt
from ..db.models import ClinicalNote


SECTIONS = ("concerns", "observations", "interventions", "medicationReported")


def content_of(note):
    return decrypt(note.payload, f"session:{note.patient_id}:{note.id}")


def scoped_note(db, patient, note_id):
    note = db.scalar(select(ClinicalNote).where(ClinicalNote.id == str(note_id), ClinicalNote.patient_id == patient.id))
    if note is None:
        raise HTTPException(404, "Session unavailable.")
    return note
