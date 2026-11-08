import base64
from datetime import date, datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
from uuid import uuid4
import zipfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException
from sqlalchemy import delete, select, text, update

from ..adapters.crypto import encrypt
from ..adapters.objectstore import get_store
from ..core.cache import get_redis, set_maintenance
from ..core.config import get_settings
from ..core.database import Base
from ..core.exceptions import KeyUnavailableError
from ..db.models import (
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
    now,
)
from ..core.security import passwords
from ..services.audit import record_audit
from ..services.authorization import has_access
from ..services.authorization import require
from ..services.raw_text import delete_raw


class PackageInvalid(Exception):
    pass


def get_backup_key(create_if_missing: bool = False) -> bytes:
    settings = get_settings()
    key_path = Path(settings.backup_key_path)
    if not key_path.exists():
        if not create_if_missing:
            raise KeyUnavailableError(f"Backup key not found at {key_path}")
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_bytes = os.urandom(32)
        encoded = base64.urlsafe_b64encode(key_bytes).decode("ascii")
        try:
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(encoded)
        except FileExistsError:
            pass
    try:
        raw_val = key_path.read_text(encoding="utf-8").strip()
    except OSError as e:
        raise KeyUnavailableError(f"Backup key unreadable at {key_path}: {e}") from None

    s = raw_val.strip()
    rem = len(s) % 4
    if rem:
        s += "=" * (4 - rem)
    try:
        key = base64.urlsafe_b64decode(s)
    except Exception as e:
        raise KeyUnavailableError(f"Malformed backup key: {e}") from None
    if len(key) != 32:
        raise KeyUnavailableError("Backup key must decode to exactly 32 bytes")
    return key


def encode_value(val):
    if isinstance(val, bytes):
        return {"__b64__": base64.b64encode(val).decode("ascii")}
    if isinstance(val, datetime):
        return {"__dt__": val.isoformat()}
    if isinstance(val, date):
        return {"__date__": val.isoformat()}
    return val


def decode_value(val):
    if isinstance(val, dict) and len(val) == 1:
        if "__b64__" in val:
            return base64.b64decode(val["__b64__"])
        if "__dt__" in val:
            return datetime.fromisoformat(val["__dt__"])
        if "__date__" in val:
            return date.fromisoformat(val["__date__"])
    return val


def decode_row(row_dict: dict) -> dict:
    return {k: decode_value(v) for k, v in row_dict.items()}


def get_current_schema(db) -> str:
    try:
        result = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
        return str(result) if result else "unversioned"
    except Exception:
        return "unversioned"


def format_manifest_summary(manifest: dict | str) -> str:
    if isinstance(manifest, str):
        return manifest
    if "summary" in manifest and isinstance(manifest["summary"], str):
        return manifest["summary"]
    row_counts = manifest.get("rowCounts", {})
    objects = manifest.get("objects", {})
    return f"{len(row_counts)} tables, {sum(row_counts.values())} rows, {len(objects)} objects"


def _allow_governed_removal(db):
    """Let this transaction alone pass the immutability triggers (PostgreSQL only)."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT set_config('sanctum.governed_removal', 'on', true)"))


def delete_patient(db, request, user, patient, reason: str):
    patient_id_str = str(patient.id)
    opaque_id = hashlib.sha256(patient_id_str.encode("utf-8")).hexdigest()

    record = db.get(DeletionRecord, opaque_id)
    encrypted_reason = encrypt({"reason": reason}, f"deletion:{opaque_id}")
    if record is None:
        record = DeletionRecord(
            opaque_id=opaque_id,
            actor_id=user.id,
            reason=encrypted_reason,
            state="deleting",
        )
        db.add(record)
    else:
        record.actor_id = user.id
        record.reason = encrypted_reason
        record.state = "deleting"

    patient.status = "deleting"
    record_audit(db, request, user, "patient.deletion_started", None)
    db.commit()

    try:
        _allow_governed_removal(db)
        docs = db.scalars(select(StoredDocument).where(StoredDocument.patient_id == patient_id_str)).all()
        store = get_store()
        for doc in docs:
            if doc.object_key:
                store.delete(doc.object_key)
            delete_raw(doc)

        doc_ids = [doc.id for doc in docs]
        if doc_ids:
            db.execute(delete(ExtractedPage).where(ExtractedPage.document_id.in_(doc_ids)))
            db.execute(delete(DocumentImport).where(DocumentImport.document_id.in_(doc_ids)))
            db.execute(delete(ExtractionJob).where(ExtractionJob.document_id.in_(doc_ids)))

        db.execute(delete(Report).where(Report.patient_id == patient_id_str))
        db.execute(delete(SummaryJob).where(SummaryJob.patient_id == patient_id_str))
        db.execute(delete(AISummary).where(AISummary.patient_id == patient_id_str))
        db.execute(delete(IndicatorRun).where(IndicatorRun.patient_id == patient_id_str))
        db.execute(delete(ConfirmedRating).where(ConfirmedRating.patient_id == patient_id_str))
        db.execute(delete(ConfirmedConcern).where(ConfirmedConcern.patient_id == patient_id_str))
        db.execute(delete(ConfirmedMedication).where(ConfirmedMedication.patient_id == patient_id_str))
        db.execute(delete(ClinicalGrant).where(ClinicalGrant.patient_id == patient_id_str))
        db.execute(delete(FollowUp).where(FollowUp.patient_id == patient_id_str))
        db.execute(delete(PatientEvent).where(PatientEvent.patient_id == patient_id_str))
        db.execute(delete(PatientAccess).where(PatientAccess.patient_id == patient_id_str))
        db.execute(delete(StoredDocument).where(StoredDocument.patient_id == patient_id_str))

        db.execute(update(ClinicalNote).where(ClinicalNote.patient_id == patient_id_str).values(parent_id=None))
        db.execute(delete(ClinicalNote).where(ClinicalNote.patient_id == patient_id_str))

        db.execute(delete(Patient).where(Patient.id == patient_id_str))

        record = db.get(DeletionRecord, opaque_id)
        if record:
            record.state = "completed"
            record.completed_at = now()

        record_audit(db, request, user, "patient.deleted", None)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(503, "Deletion could not finish. Retry it.") from exc

    return {"deleted": True}


def create_backup(db, actor_id=None, destination=None) -> BackupRecord:
    settings = get_settings()
    dest_dir = Path(destination) if destination else Path(settings.backup_path)
    dest_dir.mkdir(parents=True, exist_ok=True)

    backup_id = str(uuid4())
    store = get_store()

    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})

    db_data = {}
    row_counts = {}
    for table in Base.metadata.sorted_tables:
        if table.name == "backups":
            continue
        result = db.execute(select(table)).mappings().all()
        table_rows = []
        for r in result:
            table_rows.append({col: encode_value(r[col]) for col in r.keys()})
        db_data[table.name] = table_rows
        row_counts[table.name] = len(table_rows)

    db_json_bytes = json.dumps(db_data, sort_keys=True).encode("utf-8")
    db_digest = hashlib.sha256(db_json_bytes).hexdigest()

    objects_data = {}
    objects_digests = {}
    for doc_row in db_data.get("stored_documents", []):
        obj_key = doc_row.get("object_key")
        if obj_key:
            data = store.get(obj_key)
            objects_data[obj_key] = data
            objects_digests[obj_key] = hashlib.sha256(data).hexdigest()

    current_schema = get_current_schema(db)
    created_at_dt = now()

    summary_str = f"{len(row_counts)} tables, {sum(row_counts.values())} rows, {len(objects_digests)} objects"
    manifest = {
        "format": 1,
        "createdAt": created_at_dt.isoformat(),
        "schema": current_schema,
        "dbDigest": db_digest,
        "objects": objects_digests,
        "rowCounts": row_counts,
        "summary": summary_str,
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode("utf-8")

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", manifest_bytes)
        zf.writestr("db.json", db_json_bytes)
        for obj_key, data in objects_data.items():
            zf.writestr(f"objects/{obj_key}", data)
    zip_bytes = zip_buf.getvalue()

    backup_key = get_backup_key(create_if_missing=True)
    nonce = os.urandom(12)
    ciphertext = AESGCM(backup_key).encrypt(nonce, zip_bytes, b"sanctum-backup")
    package = b"SNCTMBK1" + nonce + ciphertext

    final_path = dest_dir / f"{backup_id}.sncbak"
    tmp_path = dest_dir / f"tmp-{uuid4().hex}"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(package)
        os.replace(tmp_path, final_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    read_back = final_path.read_bytes()
    validated_manifest = validate_package(read_back, db)

    digest = hashlib.sha256(package).hexdigest()
    size_bytes = len(package)

    record = BackupRecord(
        id=backup_id,
        created_by=actor_id,
        path=str(final_path),
        digest=digest,
        size_bytes=size_bytes,
        verified=True,
        manifest=validated_manifest,
        created_at=created_at_dt,
    )
    db.add(record)
    db.add(
        AuditEvent(
            actor_id=actor_id,
            action="backup.created",
            target_id=backup_id,
            outcome="success",
            request_id=str(uuid4()),
        )
    )
    db.commit()
    return record


def validate_package(data: bytes, db) -> dict:
    if len(data) < 8 + 12 + 16:
        raise PackageInvalid("Package truncated")
    if not data.startswith(b"SNCTMBK1"):
        raise PackageInvalid("Wrong magic bytes")

    nonce = data[8:20]
    ciphertext = data[20:]

    backup_key = get_backup_key(create_if_missing=False)
    try:
        zip_bytes = AESGCM(backup_key).decrypt(nonce, ciphertext, b"sanctum-backup")
    except InvalidTag:
        raise PackageInvalid("Decryption failed (InvalidTag or wrong key)")
    except Exception as e:
        raise PackageInvalid(f"Decryption failed: {e}")

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except Exception as e:
        raise PackageInvalid(f"Bad zip archive: {e}")

    names = zf.namelist()
    if "manifest.json" not in names or "db.json" not in names:
        raise PackageInvalid("Missing manifest.json or db.json in package")

    try:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    except Exception as e:
        raise PackageInvalid(f"Malformed manifest.json: {e}")

    if manifest.get("format") != 1:
        raise PackageInvalid(f"Unsupported format: {manifest.get('format')}")

    db_json_bytes = zf.read("db.json")
    if hashlib.sha256(db_json_bytes).hexdigest() != manifest.get("dbDigest"):
        raise PackageInvalid("db.json digest mismatch")

    current_schema = get_current_schema(db)
    if manifest.get("schema") != current_schema:
        raise PackageInvalid(f"Schema mismatch: {manifest.get('schema')} != {current_schema}")

    manifest_objects = manifest.get("objects", {})
    for obj_key, expected_digest in manifest_objects.items():
        member_name = f"objects/{obj_key}"
        if member_name not in names:
            raise PackageInvalid(f"Missing object member: {member_name}")
        obj_bytes = zf.read(member_name)
        if hashlib.sha256(obj_bytes).hexdigest() != expected_digest:
            raise PackageInvalid(f"Digest mismatch for object: {obj_key}")

    try:
        db_data = json.loads(db_json_bytes.decode("utf-8"))
    except Exception as e:
        raise PackageInvalid(f"Malformed db.json: {e}")

    for doc_row in db_data.get("stored_documents", []):
        obj_key = doc_row.get("object_key")
        if obj_key:
            if obj_key not in manifest_objects or f"objects/{obj_key}" not in names:
                raise PackageInvalid(f"StoredDocument object missing: {obj_key}")

    return manifest


def restore_package(db, data: bytes) -> dict:
    validate_package(data, db)

    nonce = data[8:20]
    ciphertext = data[20:]
    backup_key = get_backup_key(create_if_missing=False)
    zip_bytes = AESGCM(backup_key).decrypt(nonce, ciphertext, b"sanctum-backup")
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    db_data = json.loads(zf.read("db.json").decode("utf-8"))

    set_maintenance(True)
    try:
        current_deletions = db.scalars(select(DeletionRecord)).all()
        deleted_opaque_ids = {r.opaque_id for r in current_deletions}

        snapshot_deletions = db_data.get("deletion_registry", [])
        for snap_del in snapshot_deletions:
            deleted_opaque_ids.add(snap_del["opaque_id"])

        deleted_patient_ids = set()
        for p_row in db_data.get("patients", []):
            h = hashlib.sha256(str(p_row["id"]).encode("utf-8")).hexdigest()
            if h in deleted_opaque_ids:
                deleted_patient_ids.add(p_row["id"])

        deleted_doc_ids = set()
        for doc_row in db_data.get("stored_documents", []):
            if doc_row.get("patient_id") in deleted_patient_ids:
                deleted_doc_ids.add(doc_row["id"])

        store = get_store()
        doc_media_types = {
            d["object_key"]: d.get("media_type", "application/octet-stream")
            for d in db_data.get("stored_documents", [])
            if d.get("object_key")
        }

        for name in zf.namelist():
            if name.startswith("objects/"):
                obj_key = name[len("objects/"):]
                if any(
                    d.get("object_key") == obj_key
                    for d in db_data.get("stored_documents", [])
                    if d.get("id") in deleted_doc_ids
                ):
                    continue
                obj_data = zf.read(name)
                ct = doc_media_types.get(obj_key, "application/octet-stream")
                store.put(obj_key, obj_data, ct)

        _allow_governed_removal(db)
        db.execute(update(ClinicalNote).values(parent_id=None))
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in ("backups", "deletion_registry"):
                continue
            db.execute(delete(table))

        for table in Base.metadata.sorted_tables:
            if table.name == "backups":
                continue
            if table.name == "deletion_registry":
                for r in snapshot_deletions:
                    decoded = decode_row(r)
                    if db.get(DeletionRecord, decoded["opaque_id"]) is None:
                        db.execute(table.insert().values(**decoded))
                continue

            raw_rows = db_data.get(table.name, [])
            filtered_rows = []
            for r in raw_rows:
                if table.name == "patients" and r["id"] in deleted_patient_ids:
                    continue
                if "patient_id" in r and r["patient_id"] in deleted_patient_ids:
                    continue
                if "document_id" in r and r["document_id"] in deleted_doc_ids:
                    continue
                filtered_rows.append(r)

            if table.name == "clinical_notes":
                notes = [decode_row(r) for r in filtered_rows]
                notes_by_id = {n["id"]: n for n in notes}
                inserted_ids = set()
                ordered = []
                while len(ordered) < len(notes):
                    progress = False
                    for n in notes:
                        if n["id"] not in inserted_ids:
                            pid = n.get("parent_id")
                            if pid is None or pid not in notes_by_id or pid in inserted_ids:
                                ordered.append(n)
                                inserted_ids.add(n["id"])
                                progress = True
                    if not progress:
                        for n in notes:
                            if n["id"] not in inserted_ids:
                                ordered.append(n)
                                inserted_ids.add(n["id"])
                        break
                for n in ordered:
                    db.execute(table.insert().values(**n))
            else:
                decoded_rows = [decode_row(r) for r in filtered_rows]
                if decoded_rows:
                    db.execute(table.insert(), decoded_rows)

        db.execute(
            update(ExtractionJob)
            .where(ExtractionJob.state.in_(["queued", "running"]))
            .values(state="cancelled", run_id=None, lease_until=None, message="Cancelled by a restore.")
        )
        db.execute(
            update(SummaryJob)
            .where(SummaryJob.state.in_(["queued", "running"]))
            .values(state="cancelled", run_id=None, lease_until=None, message="Cancelled by a restore.")
        )

        db.commit()

        redis_client = get_redis()
        to_del = []
        for pat in ("sess:*", "user:*:sessions"):
            for k in redis_client.scan_iter(pat):
                to_del.append(k)
        if to_del:
            redis_client.delete(*to_del)
    finally:
        set_maintenance(False)

    return {"restored": True}


def delete_patient_endpoint(db, user, request, patient_id: str, data):
    if "patients:delete" not in user.capabilities or "users:manage" not in user.capabilities:
        raise HTTPException(403, "This action is outside your permissions.")
    if not has_access(db, user, patient_id, allow_deleting=True):
        raise HTTPException(404, "Patient unavailable.")
    patient = db.scalar(select(Patient).where(Patient.id == str(patient_id)).with_for_update())
    if patient is None:
        raise HTTPException(404, "Patient unavailable.")
    if not passwords.verify(data.password, user.password_hash):
        raise HTTPException(403, "Password confirmation failed.")
    if patient.status != "deleting":
        if patient.version != data.expectedVersion:
            raise HTTPException(409, "A newer version exists. Refresh and try again.")
    return delete_patient(db, request, user, patient, data.reason)


def list_backups(db, user):
    require(user, "operations:manage")
    records = db.scalars(select(BackupRecord).order_by(BackupRecord.created_at.desc())).all()
    items = []
    for r in records:
        items.append({
            "id": r.id,
            "createdAt": r.created_at.isoformat(),
            "scope": "Database and original documents",
            "verified": r.verified,
            "manifest": format_manifest_summary(r.manifest),
        })
    return {"items": items}


def trigger_backup(db, user):
    require(user, "operations:manage")
    record = create_backup(db, actor_id=user.id)
    return {
        "id": record.id,
        "createdAt": record.created_at.isoformat(),
        "scope": "Database and original documents",
        "verified": record.verified,
        "manifest": format_manifest_summary(record.manifest),
    }


def validate_restore_request(db, user, request, data):
    require(user, "operations:manage")
    if not passwords.verify(data.password, user.password_hash):
        raise HTTPException(403, "Password confirmation failed.")
    backup = db.get(BackupRecord, data.packageId)
    if backup is None:
        raise HTTPException(404, "Backup not found.")
    path = Path(backup.path)
    if not path.is_file():
        raise HTTPException(404, "Backup file not found.")
    package_bytes = path.read_bytes()
    try:
        manifest = validate_package(package_bytes, db)
        summary = format_manifest_summary(manifest)
        record_audit(db, request, user, "backup.validated", backup.id)
        db.commit()
        return {"valid": True, "manifest": summary}
    except PackageInvalid:
        record_audit(db, request, user, "backup.rejected", backup.id)
        db.commit()
        raise HTTPException(422, "This backup failed verification. Nothing was changed.")


def perform_restore_request(db, user, request, data):
    require(user, "operations:manage")
    if not passwords.verify(data.password, user.password_hash):
        raise HTTPException(403, "Password confirmation failed.")
    backup = db.get(BackupRecord, data.packageId)
    if backup is None:
        raise HTTPException(404, "Backup not found.")
    path = Path(backup.path)
    if not path.is_file():
        raise HTTPException(404, "Backup file not found.")
    package_bytes = path.read_bytes()
    try:
        restore_package(db, package_bytes)
        record_audit(db, request, user, "backup.restored", backup.id)
        db.commit()
        return {"restored": True}
    except PackageInvalid:
        record_audit(db, request, user, "backup.rejected", backup.id)
        db.commit()
        raise HTTPException(422, "This backup failed verification. Nothing was changed.")

