"""Short-lived machine-extracted draft text in Redis, encrypted with patient-document context."""
from ..adapters.crypto import decrypt, encrypt
from ..core.cache import get_redis
from ..core.config import get_settings


def _key(doc_id: str, page: int) -> str:
    return f"ocr:{doc_id}:{page}"


def _context(patient_id: str, doc_id: str, page: int) -> str:
    return f"document-raw:{patient_id}:{doc_id}:{page}"


def put_raw(doc, page: int, payload: dict) -> None:
    settings = get_settings()
    client = get_redis()
    key = _key(doc.id, page)
    context = _context(doc.patient_id, doc.id, page)
    ciphertext = encrypt(payload, context)
    client.set(key, ciphertext, ex=settings.raw_text_ttl_seconds)


def get_raw(doc, page: int) -> dict | None:
    client = get_redis()
    key = _key(doc.id, page)
    raw = client.get(key)
    if raw is None:
        return None
    context = _context(doc.patient_id, doc.id, page)
    return decrypt(raw, context)


def delete_raw(doc) -> None:
    client = get_redis()
    count = getattr(doc, "page_count", 0) or 0
    keys = [_key(doc.id, page) for page in range(1, count + 1)]
    if keys:
        client.delete(*keys)
