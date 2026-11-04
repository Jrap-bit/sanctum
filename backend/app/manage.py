"""Local operator commands; passwords are prompted, never command-line arguments."""
import argparse
from getpass import getpass
import re
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .database import SessionLocal
from .models import AuditEvent, LoginSession, User
from .security import ROLE_CAPABILITIES, passwords


def read_password():
    password = getpass("Choose password (12–128 characters): ")
    if not 12 <= len(password) <= 128:
        raise ValueError("Password must contain 12–128 characters.")
    if password != getpass("Repeat password: "):
        raise ValueError("Passwords did not match.")
    return password


def create_user(db, username, name, role, password):
    username = username.strip().lower()
    if not re.fullmatch(r"[a-z0-9_.-]{3,64}", username):
        raise ValueError("Username must be 3–64 letters, digits, dots, underscores or hyphens.")
    if not 1 <= len(name.strip()) <= 160:
        raise ValueError("Display name must be 1–160 characters.")
    if not 12 <= len(password) <= 128:
        raise ValueError("Password must contain 12–128 characters.")
    user = User(username=username, display_name=name.strip(), password_hash=passwords.hash(password),
                capabilities=ROLE_CAPABILITIES[role], active=True)
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
    for command in ("deactivate-user", "activate-user", "reset-password"):
        commands.add_parser(command).add_argument("--username", required=True)
    args = parser.parse_args()
    try:
        with SessionLocal() as db:
            if args.command == "create-user":
                create_user(db, args.username, args.name, args.role, read_password())
                print("Account created. You can now sign in.")
                return
            new_password = read_password() if args.command == "reset-password" else None
            user = db.scalar(select(User).where(User.username == args.username.strip().lower()).with_for_update())
            if user is None:
                raise ValueError("Account not found.")
            if new_password is not None:
                user.password_hash = passwords.hash(new_password)
            else:
                user.active = args.command == "activate-user"
            # Even reactivation must never revive a previous session.
            db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
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
