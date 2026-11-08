from fastapi import HTTPException
from sqlalchemy import select

from ..adapters.crypto import decrypt
from ..db.models import ExtractionJob


def page_data(doc, row):
    if row is None:
        return {}
    return decrypt(row.payload, f"document-page:{doc.patient_id}:{doc.id}:{row.page_number}")


def page_output(doc, page_number: int, row, raw: dict | None):
    raw_text = raw.get("rawText", "") if raw else ""
    raw_available = raw is not None
    if row is not None:
        data = page_data(doc, row)
        version = row.version
        review_state = data.get("reviewState", "reviewed")
        unreadable = data.get("unreadable", False)
        included = data.get("included", not unreadable)
        corrected_text = data.get("correctedText")
        if corrected_text is None:
            corrected_text = raw_text
    else:
        version = 1
        review_state = "unreviewed"
        unreadable = raw.get("unreadable", False) if raw else False
        included = not unreadable
        corrected_text = raw_text
    return {
        "pageNumber": page_number,
        "rawText": raw_text,
        "rawTextAvailable": raw_available,
        "correctedText": corrected_text,
        "reviewState": review_state,
        "version": version,
        "included": included,
        "unreadable": unreadable,
    }


def completed(db, doc):
    if doc.withdrawn_at is not None:
        raise HTTPException(409, "Withdrawn documents cannot be reviewed or confirmed.")
    job = db.scalar(select(ExtractionJob).where(ExtractionJob.document_id == doc.id))
    if job is None or job.state != "completed":
        raise HTTPException(409, "Finish text extraction before reviewing or importing pages.")
