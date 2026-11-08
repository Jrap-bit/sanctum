import base64
import hashlib
import json
import re
import secrets
import urllib.parse
from fastapi import HTTPException
import httpx
from pydantic import BaseModel
import redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..core.cache import get_redis
from ..core.capabilities import ROLE_CAPABILITIES
from ..core.config import get_settings
from ..core.security import COOKIE_NAME
from ..core.security import dummy_hash
from ..core.security import passwords
from ..core.security import token_digest
from ..db.models import AuditEvent
from ..db.models import User
from .rate_limits import clear_failures
from .rate_limits import consume
from .rate_limits import record_failure
from .rate_limits import retry_after
from .session_store import create_session
from .session_store import create_ws_ticket
from .session_store import delete_session
from .session_store import read_session


class UserOutput(BaseModel):
    id: str
    displayName: str
    username: str
    capabilities: list[str]
    clinicTimezone: str


def public_user(user: User) -> UserOutput:
    return UserOutput(
        id=user.id,
        displayName=user.display_name,
        username=user.username,
        capabilities=user.capabilities,
        clinicTimezone=get_settings().clinic_timezone,
    )


def google_enabled() -> bool:
    settings = get_settings()
    return bool(
        settings.google_client_id
        and settings.google_client_secret
        and settings.google_client_secret.get_secret_value()
        and settings.google_redirect_uri
    )


def providers() -> dict:
    return {"google": google_enabled()}


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


def login(db, request, data) -> str:
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
    audit(db, request, "auth.login", "success", user.id)
    db.commit()
    return user.id


def logout(db, request, token: str | None) -> None:
    if token:
        user_id = read_session(token)
        if user_id:
            audit(db, request, "auth.logout", "success", user_id)
        delete_session(token)
    db.commit()


def ws_ticket(user) -> dict:
    return {"ticket": create_ws_ticket(user.id)}


def activate(db, request, data) -> dict:
    from .accounts import account_audit
    from .accounts import redeem_credential_link

    address = request.client.host if request.client else "unknown"
    if not consume("credential-address", address, 30):
        account_audit(db, request, "credential.redeem", "rate_limited")
        db.commit()
        raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
    return redeem_credential_link(db, request, data.token, data.password)


def google_login_url(next: str = "/patients") -> str:
    if not google_enabled():
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
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"


def google_callback(
    db,
    request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> tuple[str, str | None]:
    if not google_enabled():
        raise HTTPException(404, "Google sign-in is not configured.")

    def fail():
        audit(db, request, "auth.google", "denied")
        db.commit()
        return "/login?error=google", None

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
        payload = verify_google_token(id_token_raw)
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
        if not settings.google_self_signup:
            return fail()
        user = _create_google_account(db, sub, email, payload.get("name"))
        if user is None:
            return fail()

    if not user.active or not user.credentials_ready or user.password_reset_required:
        return fail()

    if not user.capabilities:
        target_next = "/choose-role"
    audit(db, request, "auth.google", "success", user.id)
    db.commit()
    return target_next, user.id


def _available_username(db, email):
    base = re.sub(r"[^a-z0-9_.-]", "", email.split("@")[0].lower())[:55]
    if len(base) < 3:
        base = f"google-{base}"
    candidate = base
    while db.scalar(select(User.id).where(User.username == candidate)) is not None:
        candidate = f"{base}-{secrets.token_hex(3)}"
    return candidate


def _create_google_account(db, sub, email, name):
    """Create a role-less account. It can do nothing until choose_role assigns authority."""
    user = User(
        username=_available_username(db, email),
        display_name=(name or email).strip()[:160],
        email=email.lower(),
        google_sub=sub,
        password_hash=passwords.hash(secrets.token_urlsafe(32)),
        capabilities=[],
        active=True,
    )
    try:
        with db.begin_nested():
            db.add(user)
            db.flush()
    except IntegrityError:
        return None
    return user


def choose_role(db, request, user, role):
    """Assign the one role a self-registered Google account picks after first sign-in."""
    if not get_settings().google_self_signup:
        raise HTTPException(404, "Role selection is not available.")
    current = db.scalar(select(User).where(User.id == user.id).with_for_update())
    if current.google_sub is None or current.capabilities:
        raise HTTPException(409, "This account already has a role.")
    current.capabilities = ROLE_CAPABILITIES[role]
    audit(db, request, "auth.role_selected", "success", current.id)
    db.commit()
    return public_user(current)
