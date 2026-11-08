from fastapi import HTTPException
from sqlalchemy import select
from ..core.security import COOKIE_NAME, token_digest
from ..db.models import LoginSession, User, now
from sqlalchemy.orm import Session

from ..db.models import AuditEvent
from .rate_limits import consume_limits


def user_from_request(request, db):
    token = request.cookies.get(COOKIE_NAME)
    row = None
    if token and len(token) <= 128:
        row = db.execute(select(User).join(LoginSession, LoginSession.user_id == User.id)
                         .where(LoginSession.token_hash == token_digest(token),
                                LoginSession.expires_at > now(), User.active.is_(True),
                                User.credentials_ready.is_(True), User.password_reset_required.is_(False))).scalar_one_or_none()
    if row is None:
        raise HTTPException(401, "Sign in to continue.")
    return row


def audit(db, request, action, outcome, user_id=None):
    db.add(AuditEvent(actor_id=user_id, target_id=user_id, action=action, outcome=outcome,
                      request_id=request.state.request_id))


def limit_login(db: Session, username: str, address: str) -> bool:
    return consume_limits(db, [("account", username, 10), ("address", address, 100)])
