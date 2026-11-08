"""Patient-scoped grants with independent approval and revocation."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from fastapi import Request
from pydantic import Field
from pydantic import field_validator

from ..services import grants as grants_service
from .deps import CurrentUser
from .deps import Db
from .schemas import Input
from .schemas import VersionInput


router = APIRouter(prefix="/api/v1/access/grants", tags=["Access requests"])


class NewRequest(Input):
    patientId: UUID
    capability: Literal["clinical:read", "clinical:write"]
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def clean(cls, v):
        if not v.strip():
            raise ValueError("Explain why access is needed.")
        return v.strip()


class Decision(VersionInput):
    decision: Literal["approve", "deny"]
    comment: str = Field(min_length=1, max_length=2000)

    @field_validator("comment")
    @classmethod
    def clean(cls, v):
        if not v.strip():
            raise ValueError("Explain this decision.")
        return v.strip()


class Revoke(VersionInput):
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def clean(cls, v):
        if not v.strip():
            raise ValueError("Explain why access is being revoked.")
        return v.strip()


@router.get("")
def listing(user: CurrentUser, db: Db, request: Request):
    return grants_service.listing(db, user, request)


@router.post("", status_code=201)
def create(data: NewRequest, user: CurrentUser, db: Db, request: Request):
    return grants_service.create(db, user, request, data)


@router.post("/{grant_id}/review")
def review(grant_id: UUID, data: Decision, user: CurrentUser, db: Db, request: Request):
    return grants_service.review(db, user, request, grant_id, data)


@router.post("/{grant_id}/revoke")
def revoke(grant_id: UUID, data: Revoke, user: CurrentUser, db: Db, request: Request):
    return grants_service.revoke(db, user, request, grant_id, data)


@router.post("/{grant_id}/cancel")
def cancel(grant_id: UUID, data: VersionInput, user: CurrentUser, db: Db, request: Request):
    return grants_service.cancel(db, user, request, grant_id, data)
