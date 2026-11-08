from hashlib import sha256
import json
from uuid import uuid4

from fastapi import HTTPException
from fastapi import Response
from sqlalchemy import select

from ..adapters.crypto import decrypt
from ..adapters.crypto import encrypt
from ..adapters.preview_page import render_isolated
from ..db.models import ClinicalNote
from ..db.models import DocumentImport
from ..db.models import ExtractedPage
from ..db.models import ExtractionJob
from ..db.models import now
from .audit import record_audit
from .authorization import require
from .documents import original_bytes
from . import processing as processing_service
from .raw_text import get_raw
from .sessions import SECTIONS


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


def save_review(db, user, request, patient_id, document_id, page_number, data):
    doc = processing_service.find_document(db, user, patient_id, document_id, write=True)
    completed(db, doc)
    if db.get(DocumentImport, doc.id):
        raise HTTPException(409, "This document is already imported. Amend its historical notes to make corrections.")
    if not 1 <= page_number <= doc.page_count:
        raise HTTPException(404, "Page unavailable.")
    row = db.get(ExtractedPage, (doc.id, page_number))
    if row is None:
        if data.expectedVersion != 1:
            raise HTTPException(409, "This page changed since you opened it. Compare the latest version before saving.")
        row = ExtractedPage(document_id=doc.id, page_number=page_number, version=2)
        db.add(row)
    else:
        if row.version != data.expectedVersion:
            raise HTTPException(409, "This page changed since you opened it. Compare the latest version before saving.")
        row.version += 1

    content = {
        "correctedText": data.correctedText,
        "included": data.included,
        "unreadable": data.unreadable,
        "reviewState": "reviewed",
        "reviewedBy": user.id,
        "reviewedAt": now().isoformat(),
    }
    row.payload = encrypt(content, f"document-page:{doc.patient_id}:{doc.id}:{page_number}")
    doc.review_version += 1
    record_audit(db, request, user, "document.page_reviewed", doc.id)
    db.flush()
    raw = get_raw(doc, page_number)
    result = {**page_output(doc, page_number, row, raw), "documentVersion": doc.review_version}
    db.commit()
    return result


def confirm_import(db, user, request, patient_id, document_id, data):
    require(user, "clinical:write")
    doc = processing_service.find_document(db, user, patient_id, document_id, write=True)
    completed(db, doc)
    canonical = [group.model_dump(mode="json") for group in data.groups]
    canonical.sort(key=lambda g: g["pageNumbers"])
    signature = sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
    existing = db.get(DocumentImport, doc.id)
    if existing:
        prior = decrypt(existing.payload, f"document-import:{doc.patient_id}:{doc.id}")
        if prior["signature"] != signature:
            raise HTTPException(409, "This document was already imported with different groups. Open the existing notes.")
        record_audit(db, request, user, "document.import_replayed", doc.id)
        db.commit()
        return prior["result"]

    if doc.review_version != data.expectedVersion:
        raise HTTPException(409, "Page reviews changed. Reload the document and check your groups before confirming.")

    rows = db.scalars(
        select(ExtractedPage)
        .where(ExtractedPage.document_id == doc.id)
        .order_by(ExtractedPage.page_number)
    ).all()
    if len(rows) != doc.page_count:
        raise HTTPException(422, "Review and save every page, including excluded pages, before confirming.")

    pages = {row.page_number: (row, page_data(doc, row)) for row in rows}
    if any(p.get("reviewState") != "reviewed" for _, p in pages.values()):
        raise HTTPException(422, "Review and save every page, including excluded pages, before confirming.")

    included = {n for n, (_, p) in pages.items() if p.get("included", True)}
    selected = [n for group in data.groups for n in group.pageNumbers]
    if len(selected) != len(set(selected)) or set(selected) != included:
        raise HTTPException(422, "Assign every included page to exactly one session group. Do not assign excluded pages.")
    if any(p.get("unreadable") or not p.get("correctedText", "").strip() for n, (_, p) in pages.items() if n in included):
        raise HTTPException(422, "Included pages must have readable, reviewed text.")

    filename = decrypt(doc.metadata_payload, f"document-meta:{doc.patient_id}:{doc.id}")["filename"]
    imported_at = now()
    items = []
    for group in data.groups:
        text = "\n\n".join(f"[Source page {n}]\n{pages[n][1]['correctedText']}" for n in group.pageNumbers)
        if len(text) > 100000:
            raise HTTPException(422, "A session group exceeds 100,000 characters. Split it into smaller groups.")
        note_id = str(uuid4())
        source = {
            "documentId": doc.id,
            "filename": filename,
            "pageNumbers": group.pageNumbers,
            "pageVersions": [pages[n][0].version for n in group.pageNumbers],
            "importedBy": user.id,
            "importedAt": imported_at.isoformat(),
        }
        content = {
            "text": text,
            **{section: [] for section in SECTIONS},
            "amendmentReason": None,
            "source": source,
            "dateStatus": group.dateStatus,
        }
        db.add(
            ClinicalNote(
                id=note_id,
                patient_id=doc.patient_id,
                author_id=user.id,
                event_date=group.eventDate,
                state="finalized",
                version=1,
                finalized_at=imported_at,
                updated_at=imported_at,
                payload=encrypt(content, f"session:{doc.patient_id}:{note_id}"),
            )
        )
        items.append(
            {
                "id": note_id,
                "pageNumbers": group.pageNumbers,
                "dateStatus": group.dateStatus,
                "eventDate": group.eventDate.isoformat() if group.eventDate else None,
                "href": f"/patients/{doc.patient_id}/sessions/{note_id}",
            }
        )
        record_audit(db, request, user, "session.history_imported", note_id)

    doc.review_version += 1
    result = {"documentId": doc.id, "version": doc.review_version, "sessions": items}
    db.add(
        DocumentImport(
            document_id=doc.id,
            payload=encrypt({"signature": signature, "result": result}, f"document-import:{doc.patient_id}:{doc.id}"),
        )
    )
    record_audit(db, request, user, "document.history_confirmed", doc.id)
    db.commit()
    return result


def preview_page(db, user, request, patient_id, document_id, page_number):
    doc = processing_service.find_document(db, user, patient_id, document_id)
    if not 1 <= page_number <= doc.page_count:
        raise HTTPException(404, "Page unavailable.")
    png = render_isolated(original_bytes(doc), doc.media_type, page_number)
    record_audit(db, request, user, "document.page_previewed", doc.id)
    db.commit()
    return Response(
        png,
        media_type="image/png",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
