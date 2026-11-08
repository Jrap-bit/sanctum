import base64
import json
import os
import stat
from pathlib import Path
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..core.config import get_settings
from ..core.exceptions import CiphertextIntegrityError, KeyUnavailableError


def _b64url_decode(s: str | bytes) -> bytes:
    if isinstance(s, str):
        s = s.encode("ascii")
    s = s.strip()
    rem = len(s) % 4
    if rem:
        s += b"=" * (4 - rem)
    try:
        return base64.urlsafe_b64decode(s)
    except Exception as e:
        raise KeyUnavailableError(f"Malformed base64url data: {e}") from None


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _load_master_key() -> bytes:
    settings = get_settings()
    if settings.master_key is not None:
        raw_val = settings.master_key.get_secret_value()
    else:
        path = settings.master_key_path
        try:
            raw_val = path.read_text(encoding="utf-8").strip()
        except OSError as e:
            raise KeyUnavailableError(f"Master key file unreadable at {path}: {e}") from None

    key_bytes = _b64url_decode(raw_val)
    if len(key_bytes) != 32:
        raise KeyUnavailableError("Master key must decode to exactly 32 bytes")
    return key_bytes


class _KeyCache:
    def __init__(self, active_id: str, keys: dict[str, AESGCM]):
        self.active_id = active_id
        self.keys = keys


_cache: _KeyCache | None = None


def reload_keys() -> None:
    global _cache
    _cache = None


def _get_cache() -> _KeyCache:
    global _cache
    if _cache is not None:
        return _cache

    master_key = _load_master_key()
    master_aes = AESGCM(master_key)

    settings = get_settings()
    path = settings.wrapped_keys_path
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        raise KeyUnavailableError(f"Data-keys file unreadable at {path}: {e}") from None

    try:
        data = json.loads(content)
    except Exception as e:
        raise KeyUnavailableError(f"Data-keys file is malformed JSON: {e}") from None

    if not isinstance(data, dict) or "active" not in data or "keys" not in data:
        raise KeyUnavailableError("Data-keys file missing required fields")

    active_id = data["active"]
    if not isinstance(active_id, str) or not isinstance(data["keys"], dict):
        raise KeyUnavailableError("Data-keys file structure is invalid")

    unwrapped: dict[str, AESGCM] = {}
    for kid, wrapped_b64 in data["keys"].items():
        if not isinstance(kid, str) or not isinstance(wrapped_b64, str):
            raise KeyUnavailableError("Invalid key id or wrapped data key")
        wrapped = _b64url_decode(wrapped_b64)
        if len(wrapped) < 12 + 16:
            raise KeyUnavailableError(f"Wrapped key {kid} is truncated")
        nonce = wrapped[:12]
        ciphertext = wrapped[12:]
        aad = f"sanctum-data-key:{kid}".encode("ascii")
        try:
            dek = master_aes.decrypt(nonce, ciphertext, aad)
        except InvalidTag:
            raise KeyUnavailableError(f"Failed to unwrap data key {kid}") from None
        if len(dek) != 32:
            raise KeyUnavailableError(f"Data key {kid} must be 32 bytes")
        unwrapped[kid] = AESGCM(dek)

    if active_id not in unwrapped:
        raise KeyUnavailableError(f"Active key {active_id} is not among available data keys")

    _cache = _KeyCache(active_id=active_id, keys=unwrapped)
    return _cache


def encrypt_bytes(data: bytes, context: str) -> bytes:
    cache = _get_cache()
    kid = cache.active_id
    aesgcm = cache.keys[kid]
    nonce = os.urandom(12)
    aad = context.encode("utf-8")
    ct = aesgcm.encrypt(nonce, data, aad)
    return b"SNCTM1" + kid.encode("ascii") + nonce + ct


def decrypt_bytes(payload: bytes, context: str) -> bytes:
    if len(payload) < 38 or not payload.startswith(b"SNCTM1"):
        raise CiphertextIntegrityError("Invalid magic or truncated ciphertext")
    try:
        kid = payload[6:10].decode("ascii")
    except UnicodeDecodeError:
        raise CiphertextIntegrityError("Invalid key id encoding")

    cache = _get_cache()
    if kid not in cache.keys:
        raise CiphertextIntegrityError(f"Unknown key id: {kid}")

    aesgcm = cache.keys[kid]
    nonce = payload[10:22]
    ciphertext = payload[22:]
    aad = context.encode("utf-8")
    try:
        return aesgcm.decrypt(nonce, ciphertext, aad)
    except InvalidTag:
        raise CiphertextIntegrityError("Authentication failed") from None


def encrypt(data: dict, context: str) -> bytes:
    raw = json.dumps(data).encode("utf-8")
    return encrypt_bytes(raw, context)


def decrypt(payload: bytes, context: str) -> dict:
    raw = decrypt_bytes(payload, context)
    return json.loads(raw)


def initialize_key() -> None:
    settings = get_settings()
    wrapped_path = settings.wrapped_keys_path
    master_path = settings.master_key_path

    wrapped_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(wrapped_path.parent, 0o700)
    if master_path.parent != wrapped_path.parent:
        master_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(master_path.parent, 0o700)

    if wrapped_path.exists():
        reload_keys()
        _get_cache()
        print("Existing encryption key retained.")
        return

    if settings.master_key is None and not master_path.exists():
        master_raw = os.urandom(32)
        master_b64 = _b64url_encode(master_raw) + "\n"
        fd = os.open(master_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(master_b64)
        os.chmod(master_path, 0o600)

    master_key = _load_master_key()
    master_aes = AESGCM(master_key)

    kid = "k001"
    dek = os.urandom(32)
    nonce = os.urandom(12)
    aad = f"sanctum-data-key:{kid}".encode("ascii")
    wrapped_val = _b64url_encode(nonce + master_aes.encrypt(nonce, dek, aad))
    data = {"active": kid, "keys": {kid: wrapped_val}}

    fd = os.open(wrapped_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2) + "\n")
    os.chmod(wrapped_path, 0o600)

    reload_keys()
    print("Local encryption key created. Keep it with your recovery material; do not commit it.")


def rotate_key() -> str:
    settings = get_settings()
    wrapped_path = settings.wrapped_keys_path
    try:
        content = wrapped_path.read_text(encoding="utf-8")
        data = json.loads(content)
    except Exception as e:
        raise KeyUnavailableError(f"Cannot read data-keys file to rotate: {e}") from None

    keys_dict = data.get("keys", {})
    max_num = 0
    for kid in keys_dict:
        if kid.startswith("k") and kid[1:].isdigit():
            num = int(kid[1:])
            if num > max_num:
                max_num = num
    next_num = max_num + 1
    new_kid = f"k{next_num:03d}"

    master_key = _load_master_key()
    master_aes = AESGCM(master_key)

    new_dek = os.urandom(32)
    nonce = os.urandom(12)
    aad = f"sanctum-data-key:{new_kid}".encode("ascii")
    wrapped_val = _b64url_encode(nonce + master_aes.encrypt(nonce, new_dek, aad))

    keys_dict[new_kid] = wrapped_val
    data["active"] = new_kid
    data["keys"] = keys_dict

    temp_path = wrapped_path.parent / f"tmp-{uuid4().hex}.json"
    fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2) + "\n")
    os.chmod(temp_path, 0o600)
    os.replace(temp_path, wrapped_path)

    reload_keys()
    return new_kid


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["rotate"]:
        print(rotate_key())
    else:
        initialize_key()
