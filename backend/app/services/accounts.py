"""Account lifecycle shared by the admin API, activation route and local commands."""
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy import select
import secrets

from ..core.config import get_settings
from ..core.security import COOKIE_NAME
from ..core.security import passwords
from ..core.security import token_digest
from ..db.models import AuditEvent
from ..db.models import CredentialToken
from ..db.models import LoginSession
from ..db.models import User
from ..db.models import now


def account_audit(db, request, action, outcome="success", *, actor_id=None, target_id=None):
    db.add(AuditEvent(actor_id=actor_id, target_id=target_id, action=action, outcome=outcome,
                      request_id=request.state.request_id))


def invalidate_credentials(db, user_id):
    """Call while holding the user row lock; old sessions/links must not come back."""
    db.execute(delete(LoginSession).where(LoginSession.user_id == user_id))
    db.execute(delete(CredentialToken).where(CredentialToken.user_id == user_id))


def issue_credential_link(db, user, issuer_id, purpose):
    invalidate_credentials(db, user.id)
    settings = get_settings()
    expiry = now() + (timedelta(hours=settings.activation_token_hours) if purpose == "activation"
                      else timedelta(minutes=settings.reset_token_minutes))
    raw = secrets.token_urlsafe(32)
    db.add(CredentialToken(token_hash=token_digest(raw), user_id=user.id,
                           issued_by=issuer_id, purpose=purpose, expires_at=expiry))
    if purpose == "reset":
        # Suspend old-password login immediately, until the new password is chosen.
        user.password_reset_required = True
    return {"purpose": purpose, "url": settings.allowed_origin.rstrip("/") + "/activate?token=" + raw,
            "expiresAt": expiry}


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
    token = db.scalar(select(CredentialToken).where(CredentialToken.token_hash == digest,
                      CredentialToken.expires_at > now(), CredentialToken.consumed_at.is_(None)).with_for_update())
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
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    account_audit(db, request, "credential." + token.purpose, actor_id=user.id, target_id=user.id)
    db.commit()
    return {"success": True}


def administrator(db, actor, request, target_id=None):
    # Stable ordering avoids A→B / B→A row-lock deadlocks between administrators.
    ids = {actor.id, str(target_id)} if target_id is not None else {actor.id}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids)).order_by(User.id)
                                        .with_for_update().execution_options(populate_existing=True))}
    current = users.get(actor.id)
    if current is None or not current.active or not current.credentials_ready or current.password_reset_required:
        raise HTTPException(401, "Sign in to continue.")
    live_session = db.scalar(select(LoginSession.token_hash).where(
        LoginSession.token_hash == token_digest(request.cookies.get(COOKIE_NAME, "")),
        LoginSession.user_id == current.id, LoginSession.expires_at > now()))
    if live_session is None:
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
