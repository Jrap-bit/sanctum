import base64
import hashlib
import json
import secrets
import urllib.parse
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from fastapi.responses import RedirectResponse
import httpx
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from sqlalchemy import select

from ..core.cache import get_redis
from ..core.config import get_settings
from ..core.security import COOKIE_NAME
from ..core.security import dummy_hash
from ..core.security import passwords
from ..core.security import token_digest
from ..db.models import User
from ..services import auth as auth_service
from ..services.accounts import account_audit
from ..services.accounts import redeem_credential_link
from ..services.auth import audit
from ..services.auth import issue_session
from ..services.auth import login_delay
from ..services.auth import verify_google_token
from ..services.rate_limits import clear_failures
from ..services.rate_limits import consume
from ..services.rate_limits import record_failure
from ..services.session_store import create_ws_ticket
from ..services.session_store import delete_session
from ..services.session_store import read_session
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
    return UserOutput(
        id=user.id,
        displayName=user.display_name,
        username=user.username,
        capabilities=user.capabilities,
        clinicTimezone=get_settings().clinic_timezone,
    )


def _google_enabled() -> bool:
    settings = get_settings()
    return bool(
        settings.google_client_id
        and settings.google_client_secret
        and settings.google_client_secret.get_secret_value()
        and settings.google_redirect_uri
    )


@router.post("/login")
def login(data: LoginInput, request: Request, response: Response, db: Db):
    address = request.client.host if request.client else "unknown"
    delay = login_delay(data.username, address)
    if delay > 0:
        audit(db, request, "auth.login", "rate_limited")
        db.commit()
        raise HTTPException(
            429,
            "Too many sign-in attempts. Try again shortly.",
            headers={"Retry-After": str(delay)},
        )
    user = db.scalar(select(User).where(User.username == data.username).with_for_update())
    valid = passwords.verify(data.password, user.password_hash if user else dummy_hash)
    if not valid or user is None or not user.active or not user.credentials_ready or user.password_reset_required:
        record_failure("account", data.username, threshold=5)
        record_failure("address", address, threshold=50)
        audit(db, request, "auth.login", "denied")
        db.commit()
        raise HTTPException(401, "Invalid username or password.")
    clear_failures("account", data.username)
    old_token = request.cookies.get(COOKIE_NAME)
    issue_session(response, user.id, old_token=old_token)
    audit(db, request, "auth.login", "success", user.id)
    db.commit()
    return {"success": True}


@router.get("/me", response_model=UserOutput)
def me(user: CurrentUser):
    return public_user(user)


@router.post("/logout")
def logout(request: Request, response: Response, db: Db):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        user_id = read_session(token)
        if user_id:
            audit(db, request, "auth.logout", "success", user_id)
        delete_session(token)
    db.commit()
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
    )
    return {"success": True}


@router.post("/ws-ticket")
def ws_ticket(user: CurrentUser):
    return {"ticket": create_ws_ticket(user.id)}


class ActivateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=12, max_length=128)


@router.post("/activate")
def activate(data: ActivateInput, request: Request, db: Db):
    address = request.client.host if request.client else "unknown"
    if not consume("credential-address", address, 30):
        account_audit(db, request, "credential.redeem", "rate_limited")
        db.commit()
        raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
    return redeem_credential_link(db, request, data.token, data.password)


@router.get("/providers")
def providers():
    return {"google": _google_enabled()}


@router.get("/google/login")
def google_login(next: str = "/patients"):
    if not _google_enabled():
        raise HTTPException(404, "Google sign-in is not configured.")
    target_next = next if next.startswith("/") and not next.startswith("//") else "/patients"
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge_bytes = hashlib.sha256(verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(challenge_bytes).decode("ascii").rstrip("=")

    redis_client = get_redis()
    state_key = f"oauth:{token_digest(state)}"
    redis_client.set(
        state_key,
        json.dumps({"verifier": verifier, "nonce": nonce, "next": target_next}),
        ex=600,
    )

    settings = get_settings()
    params = {
        "response_type": "code",
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"
    return RedirectResponse(auth_url, status_code=302)


@router.get("/google/callback")
def google_callback(
    request: Request,
    db: Db,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if not _google_enabled():
        raise HTTPException(404, "Google sign-in is not configured.")

    def fail():
        audit(db, request, "auth.google", "denied")
        db.commit()
        return RedirectResponse("/login?error=google", status_code=302)

    if error or not state or not code:
        return fail()

    redis_client = get_redis()
    state_key = f"oauth:{token_digest(state)}"
    raw = redis_client.getdel(state_key)
    if not raw:
        return fail()

    try:
        stored = json.loads(raw)
        verifier = stored["verifier"]
        nonce = stored["nonce"]
        target_next = stored.get("next", "/patients")
    except Exception:
        return fail()

    settings = get_settings()
    try:
        token_resp = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret.get_secret_value(),
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
            timeout=10,
        )
        if token_resp.status_code != 200:
            return fail()
        token_data = token_resp.json()
        id_token_raw = token_data.get("id_token")
        if not id_token_raw:
            return fail()
    except Exception:
        return fail()

    try:
        payload = auth_service.verify_google_token(id_token_raw)
    except Exception:
        return fail()

    if not payload or payload.get("nonce") != nonce:
        return fail()

    email_verified = payload.get("email_verified")
    if not (email_verified is True or email_verified == "true"):
        return fail()

    sub = payload.get("sub")
    email = payload.get("email")
    if not sub:
        return fail()

    user = db.scalar(select(User).where(User.google_sub == sub))
    if user is None:
        if not email:
            return fail()
        user = db.scalar(
            select(User).where(
                User.email == email.lower(),
                User.google_sub.is_(None),
            )
        )
        if user is not None:
            user.google_sub = sub

    if user is None:
        return fail()

    if not user.active or not user.credentials_ready or user.password_reset_required:
        return fail()

    response = RedirectResponse(target_next, status_code=302)
    old_token = request.cookies.get(COOKIE_NAME)
    issue_session(response, user.id, old_token=old_token)
    audit(db, request, "auth.google", "success", user.id)
    db.commit()
    return response
