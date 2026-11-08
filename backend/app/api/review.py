"""Versioned page review and atomic, duplicate-safe import of reviewed history."""
from datetime import date
from hashlib import sha256
import json
from uuid import UUID, uuid4
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import Field, model_validator
from sqlalchemy import select

from ..adapters.crypto import decrypt, encrypt
from ..db.models import ClinicalNote, DocumentImport, ExtractedPage, now
from ..services.audit import record_audit
from ..services.authorization import require
from ..services.patients import clinic_today
from ..services.processing import find_document
from ..services.raw_text import get_raw
from ..services.review import completed, page_data, page_output
from ..services.sessions import SECTIONS
from .deps import CurrentUser, Db
from .processing import PREFIX
from .schemas import Input, VersionInput


router = APIRouter(tags=["Document review"])


class PageReview(VersionInput):
    correctedText: str = Field(max_length=100000)
    included: bool
    unreadable: bool

    @model_validator(mode="after")
    def valid(self):
        if self.included and (self.unreadable or not self.correctedText.strip()):
            raise ValueError("Included pages need readable, corrected text. Exclude unreadable or empty pages.")
        return self


class SessionGroup(Input):
    pageNumbers: list[int] = Field(min_length=1, max_length=500)
    dateStatus: str
    eventDate: date | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.dateStatus not in {"known", "approximate", "unknown"}:
            raise ValueError("Choose known, approximate or unknown date status.")
        if (self.dateStatus == "unknown") != (self.eventDate is None):
            raise ValueError("Unknown dates must be blank; known or approximate dates need a date.")
        if self.eventDate and self.eventDate > clinic_today():
            raise ValueError("Historical session dates cannot be in the future.")
        if any(n < 1 for n in self.pageNumbers) or len(set(self.pageNumbers)) != len(self.pageNumbers):
            raise ValueError("Use each valid page number once.")
        self.pageNumbers = sorted(self.pageNumbers)
        return self


class ConfirmImport(VersionInput):
    groups: list[SessionGroup] = Field(min_length=1, max_length=500)


@router.patch(PREFIX + "/pages/{page_number}")
def save_review(
    patient_id: UUID,
    document_id: UUID,
    page_number: int,
    data: PageReview,
    user: CurrentUser,
    db: Db,
    request: Request,
):
    doc = find_document(db, user, patient_id, document_id, write=True)
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


@router.post(PREFIX + "/confirm")
def confirm_import(
    patient_id: UUID,
    document_id: UUID,
    data: ConfirmImport,
    user: CurrentUser,
    db: Db,
    request: Request,
):
    require(user, "clinical:write")
    doc = find_document(db, user, patient_id, document_id, write=True)
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


@router.get(PREFIX + "/pages/{page_number}/original")
def preview(
    patient_id: UUID,
    document_id: UUID,
    page_number: int,
    user: CurrentUser,
    db: Db,
    request: Request,
):
    from ..services.documents import original_bytes
    from ..adapters.preview_page import render_isolated

    doc = find_document(db, user, patient_id, document_id)
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
