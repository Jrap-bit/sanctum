"""Administrator APIs for account creation, listing and credential lifecycle."""
import re
from uuid import UUID

from fastapi import APIRouter
from fastapi import Request
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator

from ...core.capabilities import ACCOUNT_PRESETS
from ...services import accounts as accounts_service
from ...services.accounts import AccountResult
from ...services.accounts import AdminUserOutput
from ..deps import CurrentUser
from ..deps import Db


router = APIRouter(prefix="/api/v1/admin/users", tags=["Account administration"])


class CreateAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=64)
    displayName: str = Field(min_length=1, max_length=160)
    capabilities: list[str] = Field(min_length=1, max_length=17)
    email: str | None = Field(default=None, max_length=254)

    @field_validator("username")
    @classmethod
    def username_valid(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9_.-]{3,64}", value):
            raise ValueError("Use 3–64 letters, digits, dots, underscores or hyphens.")
        return value

    @field_validator("displayName")
    @classmethod
    def name_valid(cls, value):
        if not value.strip():
            raise ValueError("A display name is required.")
        return value.strip()

    @field_validator("capabilities")
    @classmethod
    def capabilities_valid(cls, value):
        chosen = set(value)
        if not any(chosen <= preset for preset in ACCOUNT_PRESETS.values()):
            raise ValueError("Choose permissions within one supported role preset. Mixed roles and patient deletion grants require separate approval.")
        return sorted(chosen)

    @field_validator("email")
    @classmethod
    def email_valid(cls, value):
        if value is None:
            return None
        value = value.strip().lower()
        if len(value) > 254 or not re.fullmatch(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
            raise ValueError("Enter a valid email address.")
        return value


@router.get("", response_model=dict[str, list[AdminUserOutput]])
def list_users(user: CurrentUser, db: Db, request: Request, active: bool | None = None):
    return accounts_service.list_users(db, user, request, active)


@router.post("", response_model=AccountResult, status_code=201)
def create_account(data: CreateAccount, user: CurrentUser, db: Db, request: Request):
    return accounts_service.create_account(db, user, request, data)


@router.post("/{user_id}/reset-credential", response_model=AccountResult)
def reset_credential(user_id: UUID, user: CurrentUser, db: Db, request: Request):
    return accounts_service.reset_credential(db, user, request, user_id)


@router.post("/{user_id}/deactivate", response_model=AccountResult)
def deactivate_user(user_id: UUID, user: CurrentUser, db: Db, request: Request):
    return accounts_service.deactivate_user(db, user, request, user_id)


@router.post("/{user_id}/reactivate", response_model=AccountResult)
def reactivate_user(user_id: UUID, user: CurrentUser, db: Db, request: Request):
    return accounts_service.reactivate_user(db, user, request, user_id)
