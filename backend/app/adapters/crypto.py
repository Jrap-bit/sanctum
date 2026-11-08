"""Authenticated encryption for local development data; key is outside PostgreSQL."""
from cryptography.fernet import Fernet
from cryptography.fernet import InvalidToken
from fastapi import HTTPException
import json
import os

from ..core.config import get_settings


def cipher():
    try:
        return Fernet(get_settings().encryption_key_path.read_bytes().strip())
    except (OSError, ValueError):
        raise HTTPException(503, "Protected storage is unavailable. Check the local encryption key.") from None


def encrypt(data: dict, context: str) -> bytes:
    # Bind the encrypted record to its identity to detect ciphertext substitution.
    return cipher().encrypt(json.dumps({"context": context, "data": data}).encode())


def decrypt(payload: bytes, context: str) -> dict:
    try:
        value = json.loads(cipher().decrypt(payload))
        if value["context"] != context:
            raise ValueError("Context mismatch")
        return value["data"]
    except (InvalidToken, ValueError, KeyError, TypeError):
        raise HTTPException(503, "Protected record could not be read.") from None


def initialize_key():
    path = get_settings().encryption_key_path
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        cipher()  # Validate existing key, but never replace it.
        print("Existing encryption key retained.")
        return
    with os.fdopen(fd, "wb") as stream:
        stream.write(Fernet.generate_key())
    print("Local encryption key created. Keep it with your recovery material; do not commit it.")


if __name__ == "__main__":
    initialize_key()
