import redis
from fastapi import HTTPException
from sqlalchemy import select

from ..core.config import get_settings
from ..core.security import COOKIE_NAME
from ..db.models import AuditEvent
from ..db.models import User
from .rate_limits import retry_after
from .session_store import create_session
from .session_store import delete_session
from .session_store import read_session


def user_from_request(request, db):
    token = request.cookies.get(COOKIE_NAME)
    if not token or len(token) > 128:
        raise HTTPException(401, "Sign in to continue.")
    try:
        user_id = read_session(token)
    except redis.RedisError:
        raise HTTPException(503, "The sign-in service is unavailable.")
    if not user_id:
        raise HTTPException(401, "Sign in to continue.")
    user = db.scalar(
        select(User).where(
            User.id == user_id,
            User.active.is_(True),
            User.credentials_ready.is_(True),
            User.password_reset_required.is_(False),
        )
    )
    if user is None:
        raise HTTPException(401, "Sign in to continue.")
    return user


def issue_session(response, user_id, old_token=None):
    if old_token:
        delete_session(old_token)
    token = create_session(user_id)
    settings = get_settings()
    lifetime = settings.session_hours * 3600
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=lifetime,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return token


def audit(db, request, action, outcome, user_id=None):
    db.add(
        AuditEvent(
            actor_id=user_id,
            target_id=user_id,
            action=action,
            outcome=outcome,
            request_id=request.state.request_id,
        )
    )


def login_delay(username: str, address: str) -> int:
    return max(
        retry_after("account", username, threshold=5),
        retry_after("address", address, threshold=50),
    )


def verify_google_token(raw: str) -> dict:
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token

    settings = get_settings()
    return id_token.verify_oauth2_token(raw, Request(), settings.google_client_id)
