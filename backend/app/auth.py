from datetime import datetime, timedelta, timezone
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import AuditEvent, LoginBucket, LoginSession, User, now
from .security import COOKIE_NAME, dummy_hash, passwords, token_digest

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])
Db = Annotated[Session, Depends(get_db)]


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize(cls, value):
        return value.strip().lower()


class UserOutput(BaseModel):
    id: str
    displayName: str
    username: str
    capabilities: list[str]
    clinicTimezone: str


def public_user(user: User):
    return UserOutput(id=user.id, displayName=user.display_name, username=user.username,
                      capabilities=user.capabilities, clinicTimezone=get_settings().clinic_timezone)


def audit(db, request, action, outcome, user_id=None):
    db.add(AuditEvent(actor_id=user_id, target_id=user_id, action=action, outcome=outcome,
                      request_id=request.state.request_id))


def limit_login(db: Session, username: str, address: str) -> bool:
    """Database-backed fixed windows shared across workers and server restarts."""
    current = now()
    window = int(current.timestamp()) // 900
    expires = datetime.fromtimestamp((window + 1) * 900, timezone.utc)
    db.execute(delete(LoginBucket).where(LoginBucket.expires_at <= current))
    permitted = True
    # Atomic increments prevent simultaneous requests from bypassing the limit.
    for scope, value, limit in [("account", username, 10), ("address", address, 100)]:
        key = token_digest(f"{scope}:{value}:{window}")
        try:
            with db.begin_nested():
                db.add(LoginBucket(key=key, attempts=0, expires_at=expires))
                db.flush()
        except IntegrityError:
            pass  # Another request already created this window's bucket.
        count = db.execute(update(LoginBucket).where(LoginBucket.key == key)
                           .values(attempts=LoginBucket.attempts + 1)
                           .returning(LoginBucket.attempts)).scalar_one()
        permitted = permitted and count <= limit
    db.commit()
    return permitted


def get_current_user(request: Request, db: Db) -> User:
    token = request.cookies.get(COOKIE_NAME)
    row = None
    if token and len(token) <= 128:
        row = db.execute(select(User).join(LoginSession, LoginSession.user_id == User.id)
                         .where(LoginSession.token_hash == token_digest(token),
                                LoginSession.expires_at > now(), User.active.is_(True))).scalar_one_or_none()
    if row is None:
        raise HTTPException(401, "Sign in to continue.")
    return row


CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post("/login")
def login(data: LoginInput, request: Request, response: Response, db: Db):
    address = request.client.host if request.client else "unknown"
    if not limit_login(db, data.username, address):
        audit(db, request, "auth.login", "rate_limited")
        db.commit()
        raise HTTPException(429, "Too many sign-in attempts. Try again in 15 minutes.")
    # Lock the user so a concurrent account disable cannot race a new session.
    user = db.scalar(select(User).where(User.username == data.username).with_for_update())
    valid = passwords.verify(data.password, user.password_hash if user else dummy_hash)
    if not valid or user is None or not user.active:
        audit(db, request, "auth.login", "denied")
        db.commit()
        raise HTTPException(401, "Invalid username or password.")
    old_token = request.cookies.get(COOKIE_NAME)
    if old_token:
        db.execute(delete(LoginSession).where(LoginSession.token_hash == token_digest(old_token)))
    db.execute(delete(LoginSession).where(LoginSession.expires_at <= now()))
    token = secrets.token_urlsafe(32)
    lifetime = get_settings().session_hours * 3600
    db.add(LoginSession(token_hash=token_digest(token), user_id=user.id,
                        expires_at=now() + timedelta(seconds=lifetime)))
    audit(db, request, "auth.login", "success", user.id)
    db.commit()
    response.set_cookie(COOKIE_NAME, token, max_age=lifetime, httponly=True,
                        secure=get_settings().cookie_secure, samesite="lax", path="/")
    return {"success": True}


@router.get("/me", response_model=UserOutput)
def me(user: CurrentUser):
    return public_user(user)


@router.post("/logout")
def logout(request: Request, response: Response, db: Db):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        session = db.get(LoginSession, token_digest(token))
        if session:
            audit(db, request, "auth.logout", "success", session.user_id)
            db.delete(session)
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True,
                           secure=get_settings().cookie_secure, samesite="lax")
    return {"success": True}
