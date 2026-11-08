"""Local operator commands; passwords are prompted, never command-line arguments."""
from getpass import getpass
import os
from pathlib import Path
import sys
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import SQLAlchemyError
from uuid import uuid4
import argparse
import re

from .adapters.crypto import decrypt, encrypt
from .core.capabilities import ROLE_CAPABILITIES
from .core.database import SessionLocal
from .core.security import passwords
from .db.models import AuditEvent, Patient, PatientAccess, User
from .services.accounts import invalidate_credentials
from .services.operations import create_backup, restore_package, validate_package, PackageInvalid
from .services.patients import event


def read_password():
    password = getpass("Choose password (12–128 characters): ")
    if not 12 <= len(password) <= 128:
        raise ValueError("Password must contain 12–128 characters.")
    if password != getpass("Repeat password: "):
        raise ValueError("Passwords did not match.")
    return password


def create_user(db, username, name, role, password, email=None):
    username = username.strip().lower()
    if not re.fullmatch(r"[a-z0-9_.-]{3,64}", username):
        raise ValueError("Username must be 3–64 letters, digits, dots, underscores or hyphens.")
    if not 1 <= len(name.strip()) <= 160:
        raise ValueError("Display name must be 1–160 characters.")
    if not 12 <= len(password) <= 128:
        raise ValueError("Password must contain 12–128 characters.")
    if email is not None:
        email = email.strip().lower()
        if len(email) > 254 or not re.fullmatch(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            raise ValueError("Invalid email address.")
    user = User(
        username=username,
        display_name=name.strip(),
        password_hash=passwords.hash(password),
        capabilities=ROLE_CAPABILITIES[role],
        active=True,
        email=email,
    )
    db.add(user)
    db.flush()
    operator_event(db, "user.create", user.id)
    db.commit()
    return user


def operator_event(db, action, user_id):
    # Null actor means a trusted host operator using this local command.
    db.add(AuditEvent(action=action, target_id=user_id, outcome="success", request_id=str(uuid4())))


def main():
    parser = argparse.ArgumentParser(description="Manage local Sanctum accounts")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-user")
    create.add_argument("--username", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--role", choices=ROLE_CAPABILITIES, default="clinician")
    create.add_argument("--email", default=None)
    for command in ("deactivate-user", "activate-user", "reset-password"):
        commands.add_parser(command).add_argument("--username", required=True)
    backup_parser = commands.add_parser("backup")
    backup_parser.add_argument("--destination", default=None)
    restore_parser = commands.add_parser("restore")
    restore_parser.add_argument("--verify-first", required=True)
    commands.add_parser("seed-synthetic")
    smoke_parser = commands.add_parser("smoke-test")
    smoke_parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    if args.command == "smoke-test":
        from .smoke import run
        success = run(args.base_url)
        sys.exit(0 if success else 1)
    try:
        with SessionLocal() as db:
            if args.command == "backup":
                dest = Path(args.destination) if args.destination else None
                record = create_backup(db, actor_id=None, destination=dest)
                print(record.path)
                print("Backup verified.")
                return
            if args.command == "restore":
                path = Path(args.verify_first)
                if not path.is_file():
                    parser.exit(1, "Backup file not found.\n")
                data = path.read_bytes()
                try:
                    validate_package(data, db)
                    print("Backup verified.")
                except PackageInvalid:
                    parser.exit(1, "Backup failed verification. Nothing was changed.\n")
                restore_package(db, data)
                return
            if args.command == "seed-synthetic":
                seed_password = os.environ.get("SANCTUM_SEED_PASSWORD", "")
                if len(seed_password) < 12:
                    parser.exit(1, "SANCTUM_SEED_PASSWORD must be at least 12 characters.\n")
                for username, role in [
                    ("clinician", "clinician"),
                    ("admin", "admin"),
                    ("oversight", "oversight"),
                    ("clinical_admin", "clinical_admin"),
                ]:
                    existing_user = db.scalar(select(User).where(User.username == username))
                    if existing_user is None:
                        create_user(db, username, username.replace("_", " ").title(), role, seed_password)

                clinician_user = db.scalar(select(User).where(User.username == "clinician"))
                oversight_user = db.scalar(select(User).where(User.username == "oversight"))
                clinical_admin_user = db.scalar(select(User).where(User.username == "clinical_admin"))

                for name in ["Avery Reed (synthetic)", "Jordan Ellis (synthetic)"]:
                    found_patient = None
                    for p in db.scalars(select(Patient)).all():
                        try:
                            prof = decrypt(p.profile, f"patient:{p.id}")
                            if prof.get("displayName") == name:
                                found_patient = p
                                break
                        except Exception:
                            pass
                    if found_patient is None:
                        patient_id = str(uuid4())
                        profile = {"displayName": name, "dateOfBirth": None}
                        patient = Patient(
                            id=patient_id,
                            profile=encrypt(profile, f"patient:{patient_id}"),
                            created_by=clinician_user.id,
                            primary_practitioner_id=clinician_user.id,
                        )
                        db.add(patient)
                        db.flush()
                        event(db, clinician_user, patient, "Patient profile created")
                        found_patient = patient

                    for u in (clinician_user, oversight_user, clinical_admin_user):
                        if not db.get(PatientAccess, (found_patient.id, u.id)):
                            db.add(PatientAccess(patient_id=found_patient.id, user_id=u.id))
                db.commit()
                return
            if args.command == "create-user":
                create_user(db, args.username, args.name, args.role, read_password(), email=args.email)
                print("Account created. You can now sign in.")
                return
            new_password = read_password() if args.command == "reset-password" else None
            user = db.scalar(select(User).where(User.username == args.username.strip().lower()).with_for_update())
            if user is None:
                raise ValueError("Account not found.")
            if new_password is not None:
                user.password_hash = passwords.hash(new_password)
                user.credentials_ready = True
                user.password_reset_required = False
            else:
                if args.command == "activate-user" and not user.credentials_ready:
                    raise ValueError("Complete activation or run reset-password to set this account's first password.")
                user.active = args.command == "activate-user"
            # Even reactivation must never revive a previous session.
            invalidate_credentials(db, user.id)
            operator_event(db, f"user.{args.command}", user.id)
            db.commit()
            print("Account updated. Previous login sessions have been removed.")
    except IntegrityError:
        parser.exit(1, "That username already exists. Choose another or use reset-password.\n")
    except SQLAlchemyError:
        parser.exit(1, "Database unavailable or not initialized. Start Docker and run: alembic upgrade head\n")
    except ValueError as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
