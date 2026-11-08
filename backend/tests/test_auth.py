from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.database import Base, get_db
from app.main import app
from app.manage import create_user
from app.db.models import AuditEvent, LoginSession, User, now
from app.core.security import COOKIE_NAME, token_digest

PASSWORD = "Synthetic-test-password-42"
ORIGIN = {"Origin": "http://localhost:3000"}


@pytest.fixture
def setup():
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
    data = client.get("/api/v1/auth/me").json()
    assert data["displayName"] == "Test Clinician"
    assert "clinical:write" in data["capabilities"]
    assert "users:manage" not in data["capabilities"]
    assert "password_hash" not in data
    with factory() as db:
        assert db.get(LoginSession, token_digest(token)) is not None
        assert db.get(LoginSession, token) is None
        assert db.scalar(select(User)).password_hash.startswith("$argon2id$")
    # A separate client using the same cookie proves the identity isn't in client memory.
    with TestClient(app) as other:
        other.cookies.set(COOKIE_NAME, token)
        assert other.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/logout", headers=ORIGIN).status_code == 200
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


@pytest.mark.parametrize("change", ["expired", "inactive"])
def test_invalidated_sessions_cannot_read_identity(setup, change):
    client, factory = setup
    assert login(client).status_code == 200
    with factory() as db:
        if change == "expired":
            db.scalar(select(LoginSession)).expires_at = now() - timedelta(seconds=1)
        else:
            db.scalar(select(User)).active = False
        db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401
    if change == "inactive":
        assert login(client).status_code == 401


@pytest.mark.parametrize("origin", [None, "null", "https://evil.example", "http://localhost:3000.evil.example"])
def test_cross_site_and_missing_origin_writes_rejected(setup, origin):
    client, _ = setup
    headers = {"Origin": origin} if origin else {}
    response = client.post("/api/v1/auth/login", json={"username": "clinician", "password": PASSWORD}, headers=headers)
    assert response.status_code == 403
    assert response.json()["code"] == "UNTRUSTED_ORIGIN"
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 403


def test_limits_persist_between_requests(setup):
    client, _ = setup
    for _ in range(10):
        assert login(client, password="wrong").status_code == 401
    response = login(client)
    assert response.status_code == 429
    assert response.json()["code"] == "RATE_LIMITED"


def test_login_rotates_existing_session(setup):
    client, factory = setup
    login(client)
    old = client.cookies.get(COOKIE_NAME)
    login(client)
    assert old != client.cookies.get(COOKIE_NAME)
    with factory() as db:
        assert db.get(LoginSession, token_digest(old)) is None


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
