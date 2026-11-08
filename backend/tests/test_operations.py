import base64
from datetime import date, datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
from uuid import uuid4
import zipfile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.adapters.crypto import encrypt, initialize_key, reload_keys
from app.adapters.objectstore import get_store, reset_store
from app.core.config import get_settings
from app.core.database import Base, get_db
from app.core.security import passwords
from app.db.models import (
    AISummary,
    AuditEvent,
    BackupRecord,
    ClinicalGrant,
    ClinicalNote,
    ConfirmedConcern,
    ConfirmedMedication,
    ConfirmedRating,
    DeletionRecord,
    DocumentImport,
    ExtractedPage,
    ExtractionJob,
    FollowUp,
    IndicatorRun,
    Patient,
    PatientAccess,
    PatientEvent,
    Report,
    StoredDocument,
    SummaryJob,
    User,
)
from app.main import app
from app.manage import create_user
from app.services.operations import (
    create_backup,
    delete_patient,
    get_backup_key,
    restore_package,
    validate_package,
    PackageInvalid,
)
from app.services.session_store import create_session
from app.core.cache import get_redis

PASSWORD = "Synthetic-patient-test-42"
HEADERS = {"Origin": "http://localhost:3000"}


@pytest.fixture
def op_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "master_key", None)
    monkeypatch.setattr(get_settings(), "master_key_path", tmp_path / "master.key")
    monkeypatch.setattr(get_settings(), "wrapped_keys_path", tmp_path / "data-keys.json")
    monkeypatch.setattr(get_settings(), "store_path", tmp_path / "storage" / "objects")
    monkeypatch.setattr(get_settings(), "backup_path", tmp_path / "storage" / "backups")
    monkeypatch.setattr(get_settings(), "backup_key_path", tmp_path / "backup.key")
    reload_keys()
    reset_store()
    initialize_key()

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    ids = {}
    with factory() as db:
        for username, role in [
            ("alice", "clinician"),
            ("bob", "clinician"),
            ("admin", "admin"),
            ("clinadmin", "clinical_admin"),
        ]:
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


def create_patient_helper(client, **extra):
    response = client.post(
        "/api/v1/patients",
        json={"displayName": "Synthetic Alex", "dateOfBirth": "2000-01-02", **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Patient Deletion Tests
# ---------------------------------------------------------------------------


def test_deletion_requires_both_capabilities_and_admin_clinician_refused(op_setup):
    client, factory, ids = op_setup
    patient = create_patient_helper(client)
    patient_id = patient["id"]

    # Clinician (alice) lacks users:manage and patients:delete
    del_resp = client.request(
        "DELETE",
        f"/api/v1/patients/{patient_id}",
        json={"password": PASSWORD, "reason": "Patient requested delete", "expectedVersion": 1},
    )
    assert del_resp.status_code == 403

    # Admin lacks patients:delete
    sign_in(client, "admin")
    del_resp = client.request(
        "DELETE",
        f"/api/v1/patients/{patient_id}",
        json={"password": PASSWORD, "reason": "Admin delete attempt", "expectedVersion": 1},
    )
    assert del_resp.status_code == 403

    # Verify patient still exists and is intact
    sign_in(client, "alice")
    get_resp = client.get(f"/api/v1/patients/{patient_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == patient_id


def test_deletion_wrong_password_and_stale_version(op_setup):
    client, factory, ids = op_setup
    patient = create_patient_helper(client)
    patient_id = patient["id"]

    # Give clinadmin access to the patient
    with factory() as db:
        db.add(PatientAccess(patient_id=patient_id, user_id=ids["clinadmin"]))
        db.commit()

    sign_in(client, "clinadmin")

    # Wrong password -> 403
    resp = client.request(
        "DELETE",
        f"/api/v1/patients/{patient_id}",
        json={"password": "WrongPassword123", "reason": "Test delete", "expectedVersion": 1},
    )
    assert resp.status_code == 403
    assert resp.json()["message"] == "Password confirmation failed."

    # Stale version -> 409
    resp = client.request(
        "DELETE",
        f"/api/v1/patients/{patient_id}",
        json={"password": PASSWORD, "reason": "Test delete", "expectedVersion": 999},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "VERSION_CONFLICT"

    # Blank reason -> 422
    resp = client.request(
        "DELETE",
        f"/api/v1/patients/{patient_id}",
        json={"password": PASSWORD, "reason": "   ", "expectedVersion": 1},
    )
    assert resp.status_code == 422


def test_deletion_removes_every_table_and_leaves_nonclinical_marker(op_setup):
    client, factory, ids = op_setup
    patient = create_patient_helper(client)
    patient_id = patient["id"]

    # Populate records across all clinical tables
    store = get_store()
    object_key = f"docs/{patient_id}/sample.pdf"
    store.put(object_key, b"EncryptedPDFBytes", "application/pdf")
    assert store.exists(object_key)

    doc_id = str(uuid4())
    note_id_parent = str(uuid4())
    note_id_child = str(uuid4())

    with factory() as db:
        db.add(PatientAccess(patient_id=patient_id, user_id=ids["clinadmin"]))
        db.add(
            StoredDocument(
                id=doc_id,
                patient_id=patient_id,
                uploaded_by=ids["alice"],
                digest="hash123",
                metadata_payload=b"meta",
                object_key=object_key,
                media_type="application/pdf",
                page_count=2,
                size_bytes=100,
            )
        )
        db.add(ExtractedPage(document_id=doc_id, page_number=1, payload=b"page1"))
        db.add(DocumentImport(document_id=doc_id, payload=b"import"))
        db.add(ExtractionJob(id=str(uuid4()), document_id=doc_id, requested_by=ids["alice"]))
        db.add(Report(id=str(uuid4()), patient_id=patient_id, created_by=ids["alice"], payload=b"rep"))
        db.add(
            SummaryJob(
                id=str(uuid4()),
                patient_id=patient_id,
                requested_by=ids["alice"],
                request_key="req1",
                request_hash="h1",
                kind="brief",
                payload=b"sumjob",
            )
        )
        db.add(AISummary(id=str(uuid4()), patient_id=patient_id, created_by=ids["alice"], kind="brief", payload=b"ai"))
        db.add(
            IndicatorRun(
                id=str(uuid4()),
                patient_id=patient_id,
                created_by=ids["alice"],
                input_digest="d",
                payload=b"ind",
                reviews=b"rev",
            )
        )
        db.add(ConfirmedRating(id=str(uuid4()), patient_id=patient_id, created_by=ids["alice"], payload=b"rat"))
        db.add(ConfirmedConcern(id=str(uuid4()), patient_id=patient_id, created_by=ids["alice"], payload=b"con"))
        db.add(ConfirmedMedication(id=str(uuid4()), patient_id=patient_id, created_by=ids["alice"], payload=b"med"))
        db.add(
            ClinicalGrant(
                id=str(uuid4()),
                patient_id=patient_id,
                subject_id=ids["bob"],
                requester_id=ids["alice"],
                capability="clinical:read",
                state="approved",
                payload=b"grant",
            )
        )
        db.add(FollowUp(id=str(uuid4()), patient_id=patient_id, created_by=ids["alice"], payload=b"follow"))
        db.add(
            PatientEvent(
                id=str(uuid4()),
                patient_id=patient_id,
                actor_id=ids["alice"],
                kind="admission",
                title="Admitted",
                version=1,
            )
        )

        # Parent note and amendment child note
        db.add(
            ClinicalNote(
                id=note_id_parent,
                patient_id=patient_id,
                author_id=ids["alice"],
                parent_id=None,
                payload=b"parent note",
                state="draft",
                version=1,
            )
        )
        db.flush()
        db.add(
            ClinicalNote(
                id=note_id_child,
                patient_id=patient_id,
                author_id=ids["alice"],
                parent_id=note_id_parent,
                payload=b"child amendment",
                state="draft",
                version=2,
            )
        )
        db.commit()

    sign_in(client, "clinadmin")

    del_resp = client.request(
        "DELETE",
        f"/api/v1/patients/{patient_id}",
        json={"password": PASSWORD, "reason": "Patient requested complete erasure", "expectedVersion": 1},
    )
    assert del_resp.status_code == 200
    assert del_resp.json() == {"deleted": True}

    # Verify stored object is deleted
    assert not store.exists(object_key)

    # Verify rows in every table deleted
    with factory() as db:
        assert db.get(Patient, patient_id) is None
        assert db.scalars(select(StoredDocument).where(StoredDocument.patient_id == patient_id)).all() == []
        assert db.scalars(select(ExtractedPage).where(ExtractedPage.document_id == doc_id)).all() == []
        assert db.scalars(select(DocumentImport).where(DocumentImport.document_id == doc_id)).all() == []
        assert db.scalars(select(ExtractionJob).where(ExtractionJob.document_id == doc_id)).all() == []
        assert db.scalars(select(Report).where(Report.patient_id == patient_id)).all() == []
        assert db.scalars(select(SummaryJob).where(SummaryJob.patient_id == patient_id)).all() == []
        assert db.scalars(select(AISummary).where(AISummary.patient_id == patient_id)).all() == []
        assert db.scalars(select(IndicatorRun).where(IndicatorRun.patient_id == patient_id)).all() == []
        assert db.scalars(select(ConfirmedRating).where(ConfirmedRating.patient_id == patient_id)).all() == []
        assert db.scalars(select(ConfirmedConcern).where(ConfirmedConcern.patient_id == patient_id)).all() == []
        assert db.scalars(select(ConfirmedMedication).where(ConfirmedMedication.patient_id == patient_id)).all() == []
        assert db.scalars(select(ClinicalGrant).where(ClinicalGrant.patient_id == patient_id)).all() == []
        assert db.scalars(select(FollowUp).where(FollowUp.patient_id == patient_id)).all() == []
        assert db.scalars(select(PatientEvent).where(PatientEvent.patient_id == patient_id)).all() == []
        assert db.scalars(select(PatientAccess).where(PatientAccess.patient_id == patient_id)).all() == []
        assert db.scalars(select(ClinicalNote).where(ClinicalNote.patient_id == patient_id)).all() == []

        # Check nonclinical DeletionRecord
        opaque_id = hashlib.sha256(patient_id.encode("utf-8")).hexdigest()
        marker = db.get(DeletionRecord, opaque_id)
        assert marker is not None
        assert marker.state == "completed"
        assert marker.completed_at is not None
        assert "Alex" not in str(marker.__dict__)
        assert marker.opaque_id == opaque_id


def test_retry_works_from_deleting_and_deleting_patient_returns_404(op_setup):
    client, factory, ids = op_setup
    patient = create_patient_helper(client)
    patient_id = patient["id"]

    with factory() as db:
        p = db.get(Patient, patient_id)
        p.status = "deleting"
        db.add(PatientAccess(patient_id=patient_id, user_id=ids["clinadmin"]))
        db.commit()

    # Deleting patient returns 404 on normal endpoints
    sign_in(client, "alice")
    assert client.get(f"/api/v1/patients/{patient_id}").status_code == 404
    assert client.get("/api/v1/patients").json()["items"] == []

    # Retry works from deleting state (and skips expectedVersion)
    sign_in(client, "clinadmin")
    resp = client.request(
        "DELETE",
        f"/api/v1/patients/{patient_id}",
        json={"password": PASSWORD, "reason": "Retry after interrupted deletion", "expectedVersion": 9999},
    )
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True}

    with factory() as db:
        assert db.get(Patient, patient_id) is None
        opaque_id = hashlib.sha256(patient_id.encode("utf-8")).hexdigest()
        marker = db.get(DeletionRecord, opaque_id)
        assert marker is not None
        assert marker.state == "completed"


# ---------------------------------------------------------------------------
# Backup & Restore Tests
# ---------------------------------------------------------------------------


def test_backup_non_operators_get_403_and_package_id_is_not_path(op_setup):
    client, factory, ids = op_setup
    sign_in(client, "alice")

    assert client.get("/api/v1/admin/operations/backups").status_code == 403
    assert client.post("/api/v1/admin/operations/backups", json={}).status_code == 403
    assert (
        client.post(
            "/api/v1/admin/operations/restore/validate",
            json={"packageId": "p1", "password": PASSWORD, "reason": "r"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/admin/operations/restore",
            json={"packageId": "p1", "password": PASSWORD, "reason": "r"},
        ).status_code
        == 403
    )

    sign_in(client, "admin")
    # Path traversal / filesystem paths are refused (not found as BackupRecord)
    assert (
        client.post(
            "/api/v1/admin/operations/restore/validate",
            json={"packageId": "/etc/passwd", "password": PASSWORD, "reason": "test"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/admin/operations/restore",
            json={"packageId": "../../backup.sncbak", "password": PASSWORD, "reason": "test"},
        ).status_code
        == 404
    )


def test_backup_roundtrip_restores_changed_and_deleted_rows(op_setup):
    client, factory, ids = op_setup
    patient = create_patient_helper(client, displayName="Initial Alex")
    patient_id = patient["id"]

    sign_in(client, "admin")
    bk_resp = client.post("/api/v1/admin/operations/backups", json={})
    assert bk_resp.status_code == 201
    package_id = bk_resp.json()["id"]
    assert bk_resp.json()["verified"] is True
    assert "tables" in bk_resp.json()["manifest"]

    # Now change patient name and delete follow-up
    sign_in(client, "alice")
    patch_resp = client.patch(
        f"/api/v1/patients/{patient_id}",
        json={"expectedVersion": 1, "displayName": "Modified Alex"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["displayName"] == "Modified Alex"

    # Restore backup
    sign_in(client, "admin")
    val_resp = client.post(
        "/api/v1/admin/operations/restore/validate",
        json={"packageId": package_id, "password": PASSWORD, "reason": "Testing restore"},
    )
    assert val_resp.status_code == 200
    assert val_resp.json()["valid"] is True

    restore_resp = client.post(
        "/api/v1/admin/operations/restore",
        json={"packageId": package_id, "password": PASSWORD, "reason": "Testing restore"},
    )
    assert restore_resp.status_code == 200
    assert restore_resp.json()["restored"] is True

    # Active data is restored to Initial Alex
    sign_in(client, "alice")
    get_resp = client.get(f"/api/v1/patients/{patient_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["displayName"] == "Initial Alex"


def test_backup_flipped_byte_refused_and_active_data_unchanged(op_setup):
    client, factory, ids = op_setup
    patient = create_patient_helper(client, displayName="Active Alex")

    sign_in(client, "admin")
    bk_resp = client.post("/api/v1/admin/operations/backups", json={})
    package_id = bk_resp.json()["id"]

    with factory() as db:
        bk_record = db.get(BackupRecord, package_id)
        backup_path = Path(bk_record.path)
        data = bytearray(backup_path.read_bytes())
        # Flip a bit in ciphertext
        data[25] ^= 0xFF
        backup_path.write_bytes(bytes(data))

    # Validate fails with 422
    val_resp = client.post(
        "/api/v1/admin/operations/restore/validate",
        json={"packageId": package_id, "password": PASSWORD, "reason": "Test"},
    )
    assert val_resp.status_code == 422
    assert val_resp.json()["message"] == "This backup failed verification. Nothing was changed."

    # Restore fails with 422
    res_resp = client.post(
        "/api/v1/admin/operations/restore",
        json={"packageId": package_id, "password": PASSWORD, "reason": "Test"},
    )
    assert res_resp.status_code == 422

    # Active data unchanged
    sign_in(client, "alice")
    get_resp = client.get(f"/api/v1/patients/{patient['id']}")
    assert get_resp.status_code == 200
    assert get_resp.json()["displayName"] == "Active Alex"


def test_backup_wrong_key_and_schema_mismatch_refused(op_setup, monkeypatch):
    client, factory, ids = op_setup
    create_patient_helper(client, displayName="Schema Test")

    sign_in(client, "admin")
    bk_resp = client.post("/api/v1/admin/operations/backups", json={})
    package_id = bk_resp.json()["id"]

    with factory() as db:
        bk_record = db.get(BackupRecord, package_id)
        orig_bytes = Path(bk_record.path).read_bytes()

    # Save valid key first
    valid_key = get_backup_key(create_if_missing=False)

    # Wrong key: replace backup.key with different 32 bytes
    wrong_key_bytes = os.urandom(32)
    get_settings().backup_key_path.write_text(base64.urlsafe_b64encode(wrong_key_bytes).decode("ascii"))

    with factory() as db:
        with pytest.raises(PackageInvalid):
            validate_package(orig_bytes, db)

    # Put correct key back in backup.key
    get_settings().backup_key_path.write_text(base64.urlsafe_b64encode(valid_key).decode("ascii"))

    # Schema mismatch: craft a package with schema = "mismatched"
    nonce = orig_bytes[8:20]
    ct = orig_bytes[20:]
    zip_bytes = AESGCM(valid_key).decrypt(nonce, ct, b"sanctum-backup")
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    manifest["schema"] = "mismatched_schema_version"
    m_bytes = json.dumps(manifest).encode("utf-8")

    new_buf = io.BytesIO()
    with zipfile.ZipFile(new_buf, "w", zipfile.ZIP_DEFLATED) as new_zf:
        new_zf.writestr("manifest.json", m_bytes)
        for name in zf.namelist():
            if name != "manifest.json":
                new_zf.writestr(name, zf.read(name))
    new_zip = new_buf.getvalue()

    new_nonce = os.urandom(12)
    new_ct = AESGCM(valid_key).encrypt(new_nonce, new_zip, b"sanctum-backup")
    bad_schema_pkg = b"SNCTMBK1" + new_nonce + new_ct

    with factory() as db:
        with pytest.raises(PackageInvalid):
            validate_package(bad_schema_pkg, db)


def test_deleted_patient_not_reintroduced_by_older_backup(op_setup):
    client, factory, ids = op_setup
    patient = create_patient_helper(client, displayName="To Be Deleted")
    patient_id = patient["id"]

    sign_in(client, "admin")
    bk_resp = client.post("/api/v1/admin/operations/backups", json={})
    package_id = bk_resp.json()["id"]

    # Delete patient
    with factory() as db:
        db.add(PatientAccess(patient_id=patient_id, user_id=ids["clinadmin"]))
        db.commit()

    sign_in(client, "clinadmin")
    del_resp = client.request(
        "DELETE",
        f"/api/v1/patients/{patient_id}",
        json={"password": PASSWORD, "reason": "Permanent erasure", "expectedVersion": 1},
    )
    assert del_resp.status_code == 200

    with factory() as db:
        assert db.get(Patient, patient_id) is None
        opaque_id = hashlib.sha256(patient_id.encode("utf-8")).hexdigest()
        assert db.get(DeletionRecord, opaque_id) is not None

    # Now restore the older backup (which contained this patient)
    sign_in(client, "admin")
    restore_resp = client.post(
        "/api/v1/admin/operations/restore",
        json={"packageId": package_id, "password": PASSWORD, "reason": "Restore older snapshot"},
    )
    assert restore_resp.status_code == 200

    # Deletion reconciliation check: deleted patient must NOT be reinserted
    with factory() as db:
        assert db.get(Patient, patient_id) is None
        assert db.scalars(select(PatientAccess).where(PatientAccess.patient_id == patient_id)).all() == []
        assert db.get(DeletionRecord, opaque_id) is not None


def test_restoring_clears_redis_sessions_and_cancels_running_jobs(op_setup):
    client, factory, ids = op_setup
    # Sign in as alice to create patient
    patient = create_patient_helper(client)

    sign_in(client, "admin")
    bk_resp = client.post("/api/v1/admin/operations/backups", json={})
    package_id = bk_resp.json()["id"]

    # Create dummy sessions in redis
    create_session(ids["alice"])
    create_session(ids["bob"])
    r_client = get_redis()
    assert len(list(r_client.scan_iter("sess:*"))) >= 2

    # Insert queued and running jobs
    job1_id = str(uuid4())
    job2_id = str(uuid4())
    with factory() as db:
        db.add(
            SummaryJob(
                id=job1_id,
                patient_id=patient["id"],
                requested_by=ids["alice"],
                request_key="k1",
                request_hash="h1",
                kind="brief",
                payload=b"p",
                state="running",
                run_id="run-1",
            )
        )
        db.add(
            SummaryJob(
                id=job2_id,
                patient_id=patient["id"],
                requested_by=ids["alice"],
                request_key="k2",
                request_hash="h2",
                kind="brief",
                payload=b"p",
                state="queued",
                run_id="run-2",
            )
        )
        db.commit()

    # Restore backup
    sign_in(client, "admin")
    res_resp = client.post(
        "/api/v1/admin/operations/restore",
        json={"packageId": package_id, "password": PASSWORD, "reason": "Testing sessions clear"},
    )
    assert res_resp.status_code == 200

    # Redis sessions cleared
    assert len(list(r_client.scan_iter("sess:*"))) == 0
    assert len(list(r_client.scan_iter("user:*:sessions"))) == 0

    # Running jobs cancelled
    with factory() as db:
        j1 = db.get(SummaryJob, job1_id)
        if j1:
            assert j1.state == "cancelled"
            assert j1.run_id is None
            assert j1.message == "Cancelled by a restore."


def test_manage_commands(op_setup, monkeypatch, tmp_path, capsys):
    from app import manage

    _, factory, _ = op_setup
    monkeypatch.setattr(manage, "SessionLocal", factory)

    # Test seed-synthetic
    monkeypatch.setenv("SANCTUM_SEED_PASSWORD", "Short")
    with pytest.raises(SystemExit):
        monkeypatch.setattr("sys.argv", ["manage.py", "seed-synthetic"])
        manage.main()

    monkeypatch.setenv("SANCTUM_SEED_PASSWORD", "SyntheticSeedPassword123!")
    monkeypatch.setattr("sys.argv", ["manage.py", "seed-synthetic"])
    manage.main()

    with factory() as db:
        for u in ("clinician", "admin", "oversight", "clinical_admin"):
            assert db.scalar(select(User).where(User.username == u)) is not None
        patients = db.scalars(select(Patient)).all()
        assert len(patients) >= 2

    # Test backup command
    dest = tmp_path / "custom_backups"
    monkeypatch.setattr("sys.argv", ["manage.py", "backup", "--destination", str(dest)])
    manage.main()
    captured = capsys.readouterr()
    assert "Backup verified." in captured.out
    backup_files = list(dest.glob("*.sncbak"))
    assert len(backup_files) == 1

    # Test restore command
    monkeypatch.setattr("sys.argv", ["manage.py", "restore", "--verify-first", str(backup_files[0])])
    manage.main()
    captured = capsys.readouterr()
    assert "Backup verified." in captured.out

    # Corrupt backup file and test restore failure
    bad_file = tmp_path / "bad.sncbak"
    bad_file.write_bytes(b"corrupt")
    monkeypatch.setattr("sys.argv", ["manage.py", "restore", "--verify-first", str(bad_file)])
    with pytest.raises(SystemExit):
        manage.main()
    captured = capsys.readouterr()
    assert "Backup failed verification. Nothing was changed." in captured.err or "Backup failed verification" in captured.out
