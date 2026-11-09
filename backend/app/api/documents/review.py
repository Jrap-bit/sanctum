"""Versioned page review and atomic, duplicate-safe import of reviewed history."""
from datetime import date
from uuid import UUID

from fastapi import APIRouter
from fastapi import Request
from pydantic import Field
from pydantic import model_validator

from ...services import review as review_service
from ...services.patients import clinic_today
from ..deps import CurrentUser
from ..deps import Db
from .processing import PREFIX
from ..schemas import Input
from ..schemas import VersionInput


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
    return review_service.save_review(db, user, request, patient_id, document_id, page_number, data)


@router.post(PREFIX + "/confirm")
def confirm_import(
    patient_id: UUID,
    document_id: UUID,
    data: ConfirmImport,
    user: CurrentUser,
    db: Db,
    request: Request,
):
    return review_service.confirm_import(db, user, request, patient_id, document_id, data)


@router.get(PREFIX + "/pages/{page_number}/original")
def preview(
    patient_id: UUID,
    document_id: UUID,
    page_number: int,
    user: CurrentUser,
    db: Db,
    request: Request,
):
    return review_service.preview_page(db, user, request, patient_id, document_id, page_number)
