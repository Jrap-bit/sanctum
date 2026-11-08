import json
import time
from datetime import timedelta
import pytest
import redis
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.cache import get_redis
from app.core.config import get_settings
from app.core.database import Base, get_db
from app.core.errors import CODES, error
from app.core.security import COOKIE_NAME, token_digest
from app.db.models import AuditEvent, User, now
from app.main import app
from app.manage import create_user
from app.services.accounts import invalidate_credentials
from app.services.rate_limits import clear_failures, record_failure, retry_after

PASSWORD = "Synthetic-test-password-42"
ORIGIN = {"Origin": "http://localhost:3000"}


@pytest.fixture
def setup():
    @app.exception_handler(HTTPException)
    async def http_error_with_headers(request, exc):
        res = error(request, exc.status_code, CODES.get(exc.status_code, "REQUEST_FAILED"), str(exc.detail))
        if exc.headers:
            for k, v in exc.headers.items():
                res.headers[k] = v
        return res

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        create_user(db, "clinician", "Test Clinician", "clinician", PASSWORD)

    def dependency():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = dependency
    with TestClient(app) as client:
        yield client, factory
    app.dependency_overrides.clear()
    engine.dispose()


def login(client, username="clinician", password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password}, headers=ORIGIN)


def test_login_me_logout_and_token_replay(setup):
    client, factory = setup
    assert client.get("/api/v1/auth/me").status_code == 401
    response = login(client, " CLINICIAN ")
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    token = client.cookies.get(COOKIE_NAME)
    assert token is not None

    # Session is stored only as digest in Redis, never raw token
    r = get_redis()
    digest = token_digest(token)
    assert r.get(f"sess:{digest}") is not None
    assert r.get(f"sess:{token}") is None

    data = client.get("/api/v1/auth/me").json()
    assert data["displayName"] == "Test Clinician"
    assert "clinical:write" in data["capabilities"]
    assert "users:manage" not in data["capabilities"]
    assert "password_hash" not in data

    # A separate client using the same cookie proves identity is not in client memory
    with TestClient(app) as other:
        other.cookies.set(COOKIE_NAME, token)
        assert other.get("/api/v1/auth/me").status_code == 200

    # Logout ends it immediately and removes session from Redis
    assert client.post("/api/v1/auth/logout", headers=ORIGIN).status_code == 200
    assert r.get(f"sess:{digest}") is None
    client.cookies.set(COOKIE_NAME, token)
    assert client.get("/api/v1/auth/me").status_code == 401

    with factory() as db:
        events = db.scalars(select(AuditEvent)).all()
        assert {e.action for e in events} >= {"user.create", "auth.login", "auth.logout"}


def test_invalid_and_unknown_credentials_are_indistinguishable(setup):
    client, _ = setup
    a = login(client, password="wrong")
    b = login(client, username="unknown")
    assert a.status_code == b.status_code == 401
    assert a.json()["message"] == b.json()["message"]
    assert COOKIE_NAME not in client.cookies


def test_idle_expiry(setup):
    client, _ = setup
    assert login(client).status_code == 200
    token = client.cookies.get(COOKIE_NAME)
    r = get_redis()
    digest = token_digest(token)
    # Simulate idle expiry by deleting session key from Redis
    r.delete(f"sess:{digest}")
    assert client.get("/api/v1/auth/me").status_code == 401


def test_absolute_lifetime(setup):
    client, factory = setup
    assert login(client).status_code == 200
    token = client.cookies.get(COOKIE_NAME)
    r = get_redis()
    digest = token_digest(token)

    # Session whose createdAt is over 8 hours old
    with factory() as db:
        user = db.scalar(select(User).where(User.username == "clinician"))
        user_id = user.id

    expired_created_at = time.time() - (8.5 * 3600)
    r.set(f"sess:{digest}", json.dumps({"userId": user_id, "createdAt": expired_created_at}))
    # Access should be refused and session deleted
    assert client.get("/api/v1/auth/me").status_code == 401
    assert r.get(f"sess:{digest}") is None


def test_deactivation_ends_every_session_immediately(setup):
    client, factory = setup
    assert login(client).status_code == 200
    token = client.cookies.get(COOKIE_NAME)
    assert client.get("/api/v1/auth/me").status_code == 200

    with factory() as db:
        user = db.scalar(select(User).where(User.username == "clinician"))
        user.active = False
        invalidate_credentials(db, user.id)
        db.commit()

    # Session is immediately dead
    assert client.get("/api/v1/auth/me").status_code == 401
    assert login(client).status_code == 401


def test_redis_failure_gives_503(setup, monkeypatch):
    client, _ = setup
    assert login(client).status_code == 200

    def broken_redis(*args, **kwargs):
        raise redis.RedisError("Connection refused")

    monkeypatch.setattr("app.services.auth.read_session", broken_redis)
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 503
    assert response.json()["message"] == "The sign-in service is unavailable."


def test_progressive_delay_and_success_clears_counter(setup):
    client, _ = setup
    # 4 bad attempts: 401
    for _ in range(4):
        assert login(client, password="wrong").status_code == 401

    # 5th bad attempt: 401 and sets block
    assert login(client, password="wrong").status_code == 401

    # 6th attempt: progressive delay blocks it with 429 and Retry-After
    res = login(client, password=PASSWORD)
    assert res.status_code == 429
    assert res.json()["code"] == "RATE_LIMITED"
    assert "Retry-After" in res.headers
    retry_val = int(res.headers["Retry-After"])
    assert retry_val > 0

    # Clear the block so next attempt is permitted
    r = get_redis()
    digest = token_digest("account:clinician")
    r.delete(f"rl:block:{digest}")

    # Successful login clears the failure counter
    success_res = login(client, password=PASSWORD)
    assert success_res.status_code == 200

    # Now bad logins can fail 4 more times before rate limited again
    for _ in range(4):
        assert login(client, password="wrong").status_code == 401


def test_ws_ticket(setup):
    client, _ = setup
    assert client.post("/api/v1/auth/ws-ticket", headers=ORIGIN).status_code == 401
    assert login(client).status_code == 200
    res = client.post("/api/v1/auth/ws-ticket", headers=ORIGIN)
    assert res.status_code == 200
    ticket = res.json().get("ticket")
    assert ticket is not None
    assert len(ticket) >= 32


def test_login_rotates_existing_session(setup):
    client, _ = setup
    login(client)
    old = client.cookies.get(COOKIE_NAME)
    login(client)
    new_token = client.cookies.get(COOKIE_NAME)
    assert old != new_token
    r = get_redis()
    assert r.get(f"sess:{token_digest(old)}") is None
    assert r.get(f"sess:{token_digest(new_token)}") is not None


def test_cross_site_and_missing_origin_writes_rejected(setup):
    client, _ = setup
    for origin in (None, "null", "https://evil.example", "http://localhost:3000.evil.example"):
        headers = {"Origin": origin} if origin else {}
        response = client.post("/api/v1/auth/login", json={"username": "clinician", "password": PASSWORD}, headers=headers)
        assert response.status_code == 403
        assert response.json()["code"] == "UNTRUSTED_ORIGIN"
        assert client.post("/api/v1/auth/logout", headers=headers).status_code == 403


def test_validation_never_echoes_password(setup):
    client, _ = setup
    response = client.post("/api/v1/auth/login", json={"username": "clinician", "password": PASSWORD, "capabilities": ["users:manage"]}, headers=ORIGIN)
    assert response.status_code == 422
    assert PASSWORD not in response.text


def test_https_cookie_setting(setup, monkeypatch):
    client, _ = setup
    monkeypatch.setattr(get_settings(), "cookie_secure", True)
    response = login(client)
    assert "Secure" in response.headers["set-cookie"]
