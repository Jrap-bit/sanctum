from datetime import timedelta
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from sqlalchemy import delete
from sqlalchemy import select
import secrets

from ..core.config import get_settings
from ..core.security import COOKIE_NAME
from ..core.security import dummy_hash
from ..core.security import passwords
from ..core.security import token_digest
from ..db.models import LoginSession
from ..db.models import User
from ..db.models import now
from ..services.accounts import account_audit
from ..services.accounts import redeem_credential_link
from ..services.auth import audit
from ..services.auth import limit_login
from ..services.rate_limits import consume_limits
from .deps import CurrentUser
from .deps import Db


router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


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
    if not valid or user is None or not user.active or not user.credentials_ready or user.password_reset_required:
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


class ActivateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=12, max_length=128)


@router.post("/activate")
def activate(data: ActivateInput, request: Request, db: Db):
    address = request.client.host if request.client else "unknown"
    if not consume_limits(db, [("credential-address", address, 30)]):
        account_audit(db, request, "credential.redeem", "rate_limited")
        db.commit()
        raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
    # Activation and password-reset links use the existing password-setting screen.
    # Completion deliberately does not create a login session.
    return redeem_credential_link(db, request, data.token, data.password)
