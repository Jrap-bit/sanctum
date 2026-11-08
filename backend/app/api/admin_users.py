"""Administrator APIs for account creation, listing and credential lifecycle."""
from datetime import datetime
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from typing import Literal
from uuid import UUID
import re
import secrets

from ..core.capabilities import ACCOUNT_PRESETS
from ..core.security import passwords
from ..db.models import User
from ..services.accounts import account_audit
from ..services.accounts import administrator
from ..services.accounts import invalidate_credentials
from ..services.accounts import issue_credential_link
from .auth import UserOutput
from .auth import public_user
from .deps import CurrentUser
from .deps import Db


router = APIRouter(prefix="/api/v1/admin/users", tags=["Account administration"])


class CreateAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=64)
    displayName: str = Field(min_length=1, max_length=160)
    capabilities: list[str] = Field(min_length=1, max_length=17)

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


class AdminUserOutput(UserOutput):
    active: bool
    credentialsReady: bool
    resetRequired: bool


class CredentialAction(BaseModel):
    purpose: Literal["activation", "reset"]
    url: str
    expiresAt: datetime


class AccountResult(BaseModel):
    user: AdminUserOutput
    credentialAction: CredentialAction | None = None


def account_output(user):
    return AdminUserOutput(**public_user(user).model_dump(), active=user.active,
                           credentialsReady=user.credentials_ready, resetRequired=user.password_reset_required)


@router.get("", response_model=dict[str, list[AdminUserOutput]])
def list_users(user: CurrentUser, db: Db, request: Request, active: bool | None = None):
    administrator(db, user, request)
    statement = select(User).order_by(User.display_name, User.id)
    if active is not None:
        statement = statement.where(User.active == active)
    items = [account_output(u) for u in db.scalars(statement)]
    account_audit(db, request, "user.list", actor_id=user.id)
    db.commit()
    return {"items": items}


@router.post("", response_model=AccountResult, status_code=201)
def create_account(data: CreateAccount, user: CurrentUser, db: Db, request: Request):
    administrator(db, user, request)
    target = User(username=data.username, display_name=data.displayName,
                  capabilities=data.capabilities, active=False, credentials_ready=False,
                  password_hash=passwords.hash(secrets.token_urlsafe(32)))
    db.add(target)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "That username already exists.") from None
    action = issue_credential_link(db, target, user.id, "activation")
    account_audit(db, request, "user.create", actor_id=user.id, target_id=target.id)
    db.flush()
    result = AccountResult(user=account_output(target), credentialAction=action)
    db.commit()
    return result


@router.post("/{user_id}/reset-credential", response_model=AccountResult)
def reset_credential(user_id: UUID, user: CurrentUser, db: Db, request: Request):
    actor, target = administrator(db, user, request, user_id)
    if actor.id == target.id:
        raise HTTPException(409, "Ask another administrator or use the local password-reset command for your own account.")
    if not target.active or not target.credentials_ready:
        raise HTTPException(409, "Reactivate this account first; pending accounts will receive a new activation link.")
    action = issue_credential_link(db, target, actor.id, "reset")
    account_audit(db, request, "user.reset_credential", actor_id=actor.id, target_id=target.id)
    db.flush()
    result = AccountResult(user=account_output(target), credentialAction=action)
    db.commit()
    return result


@router.post("/{user_id}/deactivate", response_model=AccountResult)
def deactivate_user(user_id: UUID, user: CurrentUser, db: Db, request: Request):
    actor, target = administrator(db, user, request, user_id)
    if actor.id == target.id:
        raise HTTPException(409, "You cannot deactivate your own administrator account.")
    target.active = False
    invalidate_credentials(db, target.id)
    account_audit(db, request, "user.deactivate", actor_id=actor.id, target_id=target.id)
    db.flush()
    result = AccountResult(user=account_output(target))
    db.commit()
    return result


@router.post("/{user_id}/reactivate", response_model=AccountResult)
def reactivate_user(user_id: UUID, user: CurrentUser, db: Db, request: Request):
    actor, target = administrator(db, user, request, user_id)
    if target.active:
        raise HTTPException(409, "This account is already active.")
    invalidate_credentials(db, target.id)
    action = None
    if not target.credentials_ready:
        # No chosen password exists yet: issue a fresh activation, keeping login disabled.
        action = issue_credential_link(db, target, actor.id, "activation")
    else:
        target.active = True
        if target.password_reset_required:
            action = issue_credential_link(db, target, actor.id, "reset")
    account_audit(db, request, "user.reactivate", actor_id=actor.id, target_id=target.id)
    db.flush()
    result = AccountResult(user=account_output(target), credentialAction=action)
    db.commit()
    return result
