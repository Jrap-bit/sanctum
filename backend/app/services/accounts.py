"""Account lifecycle shared by the admin API, activation route and local commands."""
from datetime import datetime
from datetime import timedelta
import secrets
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..core.config import get_settings
from ..core.security import COOKIE_NAME
from ..core.security import passwords
from ..core.security import token_digest
from ..db.models import AuditEvent
from ..db.models import CredentialToken
from ..db.models import User
from ..db.models import now
from .auth import UserOutput
from .auth import public_user
from .session_store import delete_user_sessions
from .session_store import read_session


class AdminUserOutput(UserOutput):
    active: bool
    credentialsReady: bool
    resetRequired: bool
    email: str | None = None


class CredentialAction(BaseModel):
    purpose: Literal["activation", "reset"]
    url: str
    expiresAt: datetime


class AccountResult(BaseModel):
    user: AdminUserOutput
    credentialAction: CredentialAction | None = None


def account_output(user: User) -> AdminUserOutput:
    return AdminUserOutput(
        **public_user(user).model_dump(),
        active=user.active,
        credentialsReady=user.credentials_ready,
        resetRequired=user.password_reset_required,
        email=user.email,
    )


def account_audit(db, request, action, outcome="success", *, actor_id=None, target_id=None):
    db.add(
        AuditEvent(
            actor_id=actor_id,
            target_id=target_id,
            action=action,
            outcome=outcome,
            request_id=request.state.request_id,
        )
    )


def invalidate_credentials(db, user_id):
    """Call while holding the user row lock; old sessions/links must not come back."""
    delete_user_sessions(user_id)
    db.execute(delete(CredentialToken).where(CredentialToken.user_id == user_id))


def issue_credential_link(db, user, issuer_id, purpose):
    invalidate_credentials(db, user.id)
    settings = get_settings()
    expiry = now() + (
        timedelta(hours=settings.activation_token_hours)
        if purpose == "activation"
        else timedelta(minutes=settings.reset_token_minutes)
    )
    raw = secrets.token_urlsafe(32)
    db.add(
        CredentialToken(
            token_hash=token_digest(raw),
            user_id=user.id,
            issued_by=issuer_id,
            purpose=purpose,
            expires_at=expiry,
        )
    )
    if purpose == "reset":
        # Suspend old-password login immediately, until the new password is chosen.
        user.password_reset_required = True
    return {
        "purpose": purpose,
        "url": settings.allowed_origin.rstrip("/") + "/activate?token=" + raw,
        "expiresAt": expiry,
    }


def invalid_link(db, request):
    account_audit(db, request, "credential.redeem", "denied")
    db.commit()
    raise HTTPException(400, "This link is invalid, expired or already used. Request a new link.")


def redeem_credential_link(db, request, raw, password):
    digest = token_digest(raw)
    # Find the account first, then lock the user BEFORE the token. Every lifecycle
    # operation uses this lock order to coordinate reset/deactivation/redemption.
    user_id = db.scalar(select(CredentialToken.user_id).where(CredentialToken.token_hash == digest))
    if user_id is None:
        invalid_link(db, request)
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    token = db.scalar(
        select(CredentialToken)
        .where(
            CredentialToken.token_hash == digest,
            CredentialToken.expires_at > now(),
            CredentialToken.consumed_at.is_(None),
        )
        .with_for_update()
    )
    if user is None or token is None:
        invalid_link(db, request)
    if token.purpose == "activation":
        if user.credentials_ready or user.active:
            invalid_link(db, request)
    elif not user.active or not user.credentials_ready or not user.password_reset_required:
        invalid_link(db, request)
    user.password_hash = passwords.hash(password)
    user.credentials_ready = True
    user.password_reset_required = False
    user.active = True
    token.consumed_at = now()
    delete_user_sessions(user.id)
    account_audit(db, request, "credential." + token.purpose, actor_id=user.id, target_id=user.id)
    db.commit()
    return {"success": True}


def administrator(db, actor, request, target_id=None):
    # Stable ordering avoids A→B / B→A row-lock deadlocks between administrators.
    ids = {actor.id, str(target_id)} if target_id is not None else {actor.id}
    users = {
        u.id: u
        for u in db.scalars(
            select(User)
            .where(User.id.in_(ids))
            .order_by(User.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    current = users.get(actor.id)
    if current is None or not current.active or not current.credentials_ready or current.password_reset_required:
        raise HTTPException(401, "Sign in to continue.")
    if read_session(request.cookies.get(COOKIE_NAME, "")) != current.id:
        raise HTTPException(401, "Sign in to continue.")
    if "users:manage" not in current.capabilities:
        account_audit(db, request, "user.manage", "denied", actor_id=current.id)
        db.commit()
        raise HTTPException(403, "Administrator permission is required.")
    if target_id is None:
        return current, None
    target = users.get(str(target_id))
    if target is None:
        raise HTTPException(404, "Account unavailable.")
    return current, target


def list_users(db, user, request, active: bool | None = None):
    administrator(db, user, request)
    statement = select(User).order_by(User.display_name, User.id)
    if active is not None:
        statement = statement.where(User.active == active)
    items = [account_output(u) for u in db.scalars(statement)]
    account_audit(db, request, "user.list", actor_id=user.id)
    db.commit()
    return {"items": items}


def create_account(db, user, request, data):
    administrator(db, user, request)
    target = User(
        username=data.username,
        display_name=data.displayName,
        capabilities=data.capabilities,
        email=data.email,
        active=False,
        credentials_ready=False,
        password_hash=passwords.hash(secrets.token_urlsafe(32)),
    )
    db.add(target)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        if data.email and db.scalar(select(User).where(User.email == data.email)):
            raise HTTPException(409, "That email already exists.")
        raise HTTPException(409, "That username already exists.") from None
    action = issue_credential_link(db, target, user.id, "activation")
    account_audit(db, request, "user.create", actor_id=user.id, target_id=target.id)
    db.flush()
    result = AccountResult(user=account_output(target), credentialAction=action)
    db.commit()
    return result


def reset_credential(db, user, request, user_id: UUID):
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


def deactivate_user(db, user, request, user_id: UUID):
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


def reactivate_user(db, user, request, user_id: UUID):
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
