import json
from urllib.parse import parse_qs, urlparse
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.cache import get_redis
from app.core.config import get_settings
from app.core.database import Base, get_db
from app.core.security import COOKIE_NAME, token_digest
from app.db.models import User
from app.main import app
from app.manage import create_user

PASSWORD = "Synthetic-password-42"
ORIGIN = {"Origin": "http://localhost:3000"}


@pytest.fixture
def setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        create_user(db, "clinician", "Test Clinician", "clinician", PASSWORD, email="clinician@example.com")
        create_user(db, "inactive_user", "Inactive Clinician", "clinician", PASSWORD, email="inactive@example.com")
        inactive = db.scalar(select(User).where(User.username == "inactive_user"))
        inactive.active = False
        db.commit()

    def dependency():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = dependency
    with TestClient(app) as client:
        yield client, factory
    app.dependency_overrides.clear()
    engine.dispose()


def enable_google(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", SecretStr("test-client-secret"))
    monkeypatch.setattr(settings, "google_redirect_uri", "http://localhost:8000/api/v1/auth/google/callback")


def disable_google(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", None)
    monkeypatch.setattr(settings, "google_client_secret", None)
    monkeypatch.setattr(settings, "google_redirect_uri", None)


def test_disabled_gives_404_and_google_false(setup, monkeypatch):
    client, _ = setup
    disable_google(monkeypatch)
    providers = client.get("/api/v1/auth/providers").json()
    assert providers == {"google": False}

    assert client.get("/api/v1/auth/google/login").status_code == 404
    assert client.get("/api/v1/auth/google/callback?code=abc&state=xyz").status_code == 404


def test_login_redirect_has_state_and_s256_challenge(setup, monkeypatch):
    client, _ = setup
    enable_google(monkeypatch)

    res = client.get("/api/v1/auth/google/login?next=/patients", follow_redirects=False)
    assert res.status_code == 302
    location = res.headers["location"]
    parsed = urlparse(location)
    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.google.com"
    assert parsed.path == "/o/oauth2/v2/auth"

    query = parse_qs(parsed.query)
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["test-client-id"]
    assert query["redirect_uri"] == ["http://localhost:8000/api/v1/auth/google/callback"]
    assert query["scope"] == ["openid email profile"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["prompt"] == ["select_account"]

    state = query["state"][0]
    challenge = query["code_challenge"][0]
    nonce = query["nonce"][0]
    assert state and challenge and nonce

    # Verify state is stored in Redis with verifier, nonce and next
    r = get_redis()
    raw = r.get(f"oauth:{token_digest(state)}")
    assert raw is not None
    data = json.loads(raw)
    assert data["nonce"] == nonce
    assert data["next"] == "/patients"
    assert len(data["verifier"]) >= 43


def test_callback_with_unknown_or_reused_state(setup, monkeypatch):
    client, _ = setup
    enable_google(monkeypatch)

    # Unknown state
    res = client.get("/api/v1/auth/google/callback?code=abc&state=unknown-state", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == "/login?error=google"

    # Generate legitimate state
    login_res = client.get("/api/v1/auth/google/login", follow_redirects=False)
    state = parse_qs(urlparse(login_res.headers["location"]).query)["state"][0]

    # Mock httpx and verify_google_token
    class MockTokenResponse:
        status_code = 200
        def json(self):
            return {"id_token": "valid-id-token"}

    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: MockTokenResponse())

    r = get_redis()
    raw = r.get(f"oauth:{token_digest(state)}")
    nonce = json.loads(raw)["nonce"]

    monkeypatch.setattr(
        "app.services.auth.verify_google_token",
        lambda raw_tok: {"sub": "sub-100", "email": "clinician@example.com", "email_verified": True, "nonce": nonce},
    )

    # First callback succeeds and single-use consumes state
    cb1 = client.get(f"/api/v1/auth/google/callback?code=valid-code&state={state}", follow_redirects=False)
    assert cb1.status_code == 302
    assert cb1.headers["location"] == "/patients"

    # Reused state now fails
    cb2 = client.get(f"/api/v1/auth/google/callback?code=valid-code&state={state}", follow_redirects=False)
    assert cb2.status_code == 302
    assert cb2.headers["location"] == "/login?error=google"


def test_verified_email_signs_in_and_links_sub(setup, monkeypatch):
    client, factory = setup
    enable_google(monkeypatch)

    login_res = client.get("/api/v1/auth/google/login?next=/custom-path", follow_redirects=False)
    state = parse_qs(urlparse(login_res.headers["location"]).query)["state"][0]

    r = get_redis()
    nonce = json.loads(r.get(f"oauth:{token_digest(state)}"))["nonce"]

    class MockTokenResponse:
        status_code = 200
        def json(self):
            return {"id_token": "valid-id-token"}

    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: MockTokenResponse())
    monkeypatch.setattr(
        "app.services.auth.verify_google_token",
        lambda raw_tok: {"sub": "google-sub-12345", "email": "CLINICIAN@EXAMPLE.COM", "email_verified": True, "nonce": nonce},
    )

    cb = client.get(f"/api/v1/auth/google/callback?code=valid-code&state={state}", follow_redirects=False)
    assert cb.status_code == 302
    assert cb.headers["location"] == "/custom-path"
    assert COOKIE_NAME in cb.cookies

    # User can now access /me
    me_res = client.get("/api/v1/auth/me")
    assert me_res.status_code == 200
    assert me_res.json()["displayName"] == "Test Clinician"

    # In DB, google_sub is linked
    with factory() as db:
        user = db.scalar(select(User).where(User.username == "clinician"))
        assert user.google_sub == "google-sub-12345"


def test_unknown_email_never_creates_user(setup, monkeypatch):
    client, factory = setup
    enable_google(monkeypatch)

    login_res = client.get("/api/v1/auth/google/login", follow_redirects=False)
    state = parse_qs(urlparse(login_res.headers["location"]).query)["state"][0]
    nonce = json.loads(get_redis().get(f"oauth:{token_digest(state)}"))["nonce"]

    class MockTokenResponse:
        status_code = 200
        def json(self):
            return {"id_token": "valid-id-token"}

    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: MockTokenResponse())
    monkeypatch.setattr(
        "app.services.auth.verify_google_token",
        lambda raw_tok: {"sub": "google-unknown", "email": "unknown@example.com", "email_verified": True, "nonce": nonce},
    )

    with factory() as db:
        count_before = len(db.scalars(select(User)).all())

    cb = client.get(f"/api/v1/auth/google/callback?code=valid-code&state={state}", follow_redirects=False)
    assert cb.status_code == 302
    assert cb.headers["location"] == "/login?error=google"

    with factory() as db:
        count_after = len(db.scalars(select(User)).all())
        assert count_after == count_before
        assert db.scalar(select(User).where(User.email == "unknown@example.com")) is None


def test_deactivated_user_is_refused(setup, monkeypatch):
    client, _ = setup
    enable_google(monkeypatch)

    login_res = client.get("/api/v1/auth/google/login", follow_redirects=False)
    state = parse_qs(urlparse(login_res.headers["location"]).query)["state"][0]
    nonce = json.loads(get_redis().get(f"oauth:{token_digest(state)}"))["nonce"]

    class MockTokenResponse:
        status_code = 200
        def json(self):
            return {"id_token": "valid-id-token"}

    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: MockTokenResponse())
    monkeypatch.setattr(
        "app.services.auth.verify_google_token",
        lambda raw_tok: {"sub": "google-inactive", "email": "inactive@example.com", "email_verified": True, "nonce": nonce},
    )

    cb = client.get(f"/api/v1/auth/google/callback?code=valid-code&state={state}", follow_redirects=False)
    assert cb.status_code == 302
    assert cb.headers["location"] == "/login?error=google"
    assert COOKIE_NAME not in client.cookies


def test_wrong_nonce_and_unverified_email_are_refused(setup, monkeypatch):
    client, _ = setup
    enable_google(monkeypatch)

    class MockTokenResponse:
        status_code = 200
        def json(self):
            return {"id_token": "valid-id-token"}

    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: MockTokenResponse())

    # Wrong nonce
    res1 = client.get("/api/v1/auth/google/login", follow_redirects=False)
    state1 = parse_qs(urlparse(res1.headers["location"]).query)["state"][0]
    monkeypatch.setattr(
        "app.services.auth.verify_google_token",
        lambda raw_tok: {"sub": "sub-1", "email": "clinician@example.com", "email_verified": True, "nonce": "wrong-nonce"},
    )
    cb1 = client.get(f"/api/v1/auth/google/callback?code=code1&state={state1}", follow_redirects=False)
    assert cb1.status_code == 302
    assert cb1.headers["location"] == "/login?error=google"

    # Unverified email
    res2 = client.get("/api/v1/auth/google/login", follow_redirects=False)
    state2 = parse_qs(urlparse(res2.headers["location"]).query)["state"][0]
    nonce2 = json.loads(get_redis().get(f"oauth:{token_digest(state2)}"))["nonce"]
    monkeypatch.setattr(
        "app.services.auth.verify_google_token",
        lambda raw_tok: {"sub": "sub-2", "email": "clinician@example.com", "email_verified": False, "nonce": nonce2},
    )
    cb2 = client.get(f"/api/v1/auth/google/callback?code=code2&state={state2}", follow_redirects=False)
    assert cb2.status_code == 302
    assert cb2.headers["location"] == "/login?error=google"
