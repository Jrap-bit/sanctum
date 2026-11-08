from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.adapters.crypto import initialize_key, reload_keys
from app.adapters.crypto import encrypt
from app.adapters.objectstore import reset_store
from app.core.database import Base, get_db
from app.main import app
from app.manage import create_user
from app.db.models import AuditEvent, FollowUp, Patient, PatientAccess, User
from app.core.security import COOKIE_NAME

PASSWORD = "Synthetic-patient-test-42"
HEADERS = {"Origin": "http://localhost:3000"}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "master_key", None)
    monkeypatch.setattr(get_settings(), "master_key_path", tmp_path / "master.key")
    monkeypatch.setattr(get_settings(), "wrapped_keys_path", tmp_path / "data-keys.json")
    monkeypatch.setattr(get_settings(), "store_path", tmp_path / "storage" / "objects")
    reload_keys()
    reset_store()
    initialize_key()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    ids = {}
    with factory() as db:
        for username, role in [("alice", "clinician"), ("bob", "clinician"), ("admin", "admin")]:
            ids[username] = create_user(db, username, username.title(), role, PASSWORD).id
    def dependency():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = dependency
    with TestClient(app, headers=HEADERS) as client:
        sign_in(client, "alice")
        yield client, factory, ids
    app.dependency_overrides.clear()
    engine.dispose()


def sign_in(client, username):
    response = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text


def create(client, **extra):
    response = client.post("/api/v1/patients", json={"displayName": "Synthetic Alex", "dateOfBirth": "2000-01-02", **extra})
    assert response.status_code == 201, response.text
    return response.json()


def path(patient):
    return f"/api/v1/patients/{patient['id']}"


def test_create_list_detail_and_persisted_encryption(setup):
    client, factory, ids = setup
    patient = create(client, initialPractitionerId=ids["alice"])
    assert patient["version"] == 1
    assert patient["assignment"] == "Alice"
    assert patient["allowedActions"] == ["clinical:read", "archive", "edit"]
    assert client.get("/api/v1/patients").json()["items"] == [patient]
    assert client.get("/api/v1/patients?q=alex").json()["items"] == [patient]
    assert client.get("/api/v1/patients?q=unmatched").json()["items"] == []
    token = client.cookies.get(COOKIE_NAME)
    with TestClient(app) as fresh_client:
        fresh_client.cookies.set(COOKIE_NAME, token)
        assert fresh_client.get(path(patient)).json() == patient
    with factory() as db:
        row = db.get(Patient, patient["id"])
        assert b"Synthetic Alex" not in row.profile
        assert b"2000-01-02" not in row.profile
        assert db.get(PatientAccess, (row.id, ids["alice"])) is not None
        events = db.scalars(select(AuditEvent)).all()
        assert {e.action for e in events} >= {"patient.create", "patient.read", "patient.list"}
        assert all("Alex" not in str(e.__dict__) for e in events)


@pytest.mark.parametrize("invalid", [
    {"displayName": "   "}, {"displayName": "x" * 161},
    {"dateOfBirth": (date.today() + timedelta(days=5)).isoformat()},
    {"dateOfBirth": "not-a-date"}, {"capabilities": ["users:manage"]},
])
def test_invalid_patient_rejected(setup, invalid):
    client, _, _ = setup
    assert client.post("/api/v1/patients", json={"displayName": "Test", **invalid}).status_code == 422
    assert client.get("/api/v1/patients").json()["items"] == []


def test_other_practitioner_cannot_discover_or_access_patient(setup):
    client, _, _ = setup
    patient = create(client)
    sign_in(client, "bob")
    assert client.get("/api/v1/patients").json()["items"] == []
    for suffix in ["", "/timeline", "/follow-ups"]:
        assert client.get(path(patient) + suffix).status_code == 404
    assert client.post(path(patient) + "/archive", json={"expectedVersion": 1}).status_code == 404
    assert client.post(path(patient) + "/follow-ups", json={"title": "forbidden"}).status_code == 404
    assert client.patch(path(patient), json={"expectedVersion": 1, "displayName": "forbidden"}).status_code == 404


def test_creation_cannot_grant_another_practitioner_access(setup):
    client, _, ids = setup
    assert client.post("/api/v1/patients", json={"displayName": "Test", "initialPractitionerId": ids["bob"]}).status_code == 403


def test_revoked_scope_is_checked_again(setup):
    client, factory, ids = setup
    patient = create(client)
    with factory() as db:
        db.execute(delete(PatientAccess).where(PatientAccess.patient_id == patient["id"]))
        db.commit()
    assert client.get(path(patient)).status_code == 404
    assert client.get(path(patient) + "/follow-ups").status_code == 404


def test_admin_can_create_profile_but_cannot_read_clinical_data(setup):
    client, _, ids = setup
    sign_in(client, "admin")
    users = client.get("/api/v1/admin/users")
    assert users.status_code == 200
    assert "password_hash" not in users.text
    patient = create(client, initialPractitionerId=ids["bob"])
    assert "clinical:read" not in patient["allowedActions"]
    assert client.get(path(patient)).status_code == 200
    assert client.get(path(patient) + "/timeline").status_code == 403
    assert client.get(path(patient) + "/follow-ups").status_code == 403
    sign_in(client, "bob")
    assert client.get(path(patient)).status_code == 200
    assert client.get("/api/v1/admin/users").status_code == 403


def test_update_archive_reactivate_and_version_conflict(setup):
    client, _, _ = setup
    patient = create(client)
    response = client.patch(path(patient), json={"expectedVersion": 1, "displayName": "Revised Alex", "dateOfBirth": None})
    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert response.json()["dateOfBirth"] is None
    response = client.patch(path(patient), json={"expectedVersion": 1, "displayName": "Stale save"})
    assert response.status_code == 409
    assert response.json()["code"] == "VERSION_CONFLICT"
    assert client.post(path(patient) + "/archive", json={"expectedVersion": 2}).json()["version"] == 3
    assert client.get("/api/v1/patients").json()["items"] == []
    assert client.get("/api/v1/patients?status=archived").json()["items"][0]["id"] == patient["id"]
    assert client.post(path(patient) + "/follow-ups", json={"title": "New task"}).status_code == 409
    assert client.post(path(patient) + "/reactivate", json={"expectedVersion": 3}).json()["status"] == "active"
    assert len(client.get(path(patient) + "/timeline").json()["items"]) == 4


def test_followups_keep_unknown_date_and_enforce_task_parent(setup):
    client, factory, _ = setup
    patient = create(client)
    other = create(client, displayName="Another synthetic patient")
    response = client.post(path(patient) + "/follow-ups", json={"title": "Discuss sleep", "dueDate": None})
    assert response.status_code == 201
    task = response.json()
    assert task["state"] == "open" and task["dueDate"] is None
    with factory() as db:
        assert b"Discuss sleep" not in db.get(FollowUp, task["id"]).payload
    assert client.get(path(patient) + "/follow-ups").json()["items"] == [task]
    assert client.patch(path(other) + "/follow-ups/" + task["id"], json={"state": "completed"}).status_code == 404
    task_path = path(patient) + "/follow-ups/" + task["id"]
    assert client.patch(task_path, json={"state": "completed"}).json()["state"] == "completed"
    assert client.patch(task_path, json={"state": "completed"}).status_code == 200
    assert client.patch(task_path, json={"state": "cancelled"}).status_code == 409


def test_missing_key_and_tampered_records_fail_without_plaintext(setup):
    client, factory, _ = setup
    patient = create(client)
    other = create(client, displayName="Secret other profile")
    with factory() as db:
        db.get(Patient, patient["id"]).profile = db.get(Patient, other["id"]).profile
        db.commit()
    response = client.get(path(patient))
    assert response.status_code == 500
    assert "Secret other profile" not in response.text
    get_settings().master_key_path.unlink()
    reload_keys()
    assert client.post("/api/v1/patients", json={"displayName": "Fail safely"}).status_code == 503


def test_unauthenticated_patient_access(setup):
    client, _, _ = setup
    client.cookies.clear()
    assert client.get("/api/v1/patients").status_code == 401
    assert client.post("/api/v1/patients", json={"displayName": "Test"}).status_code == 401


def test_database_rejects_two_writers_using_the_same_version(setup):
    client, factory, _ = setup
    patient = create(client)
    with factory() as first, factory() as second:
        one = first.get(Patient, patient["id"])
        two = second.get(Patient, patient["id"])
        one.profile = encrypt({"displayName": "First save", "dateOfBirth": None}, f"patient:{one.id}")
        first.commit()
        two.profile = encrypt({"displayName": "Stale save", "dateOfBirth": None}, f"patient:{two.id}")
        with pytest.raises(StaleDataError):
            second.commit()
        second.rollback()
    assert client.get(path(patient)).json()["displayName"] == "First save"


def test_audit_failure_rolls_back_patient_creation(setup, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    from app.api import patients
    client, factory, _ = setup
    def unavailable(*args):
        raise SQLAlchemyError("Synthetic audit outage")
    monkeypatch.setattr(patients, "record_audit", unavailable)
    response = client.post("/api/v1/patients", json={"displayName": "Do not commit"})
    assert response.status_code == 503
    with factory() as db:
        assert db.scalar(select(Patient)) is None
