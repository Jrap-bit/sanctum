"""Server-side login sessions in Redis. Only token digests are ever stored."""
import json
import secrets
import time

from ..core.cache import get_redis
from ..core.config import get_settings
from ..core.security import token_digest


def _session_key(digest):
    return f"sess:{digest}"


def _user_key(user_id):
    return f"user:{user_id}:sessions"


def _ticket_key(digest):
    return f"ws-ticket:{digest}"


def _remaining_ttl(created_at):
    settings = get_settings()
    remaining = int(created_at + settings.session_hours * 3600 - time.time())
    return min(settings.session_idle_minutes * 60, remaining)


def create_session(user_id):
    """Create a session and return the raw token, which exists only in the user's cookie."""
    token = secrets.token_urlsafe(32)
    digest = token_digest(token)
    client = get_redis()
    created_at = time.time()
    client.set(_session_key(digest), json.dumps({"userId": user_id, "createdAt": created_at}),
               ex=_remaining_ttl(created_at))
    client.sadd(_user_key(user_id), digest)
    client.expire(_user_key(user_id), get_settings().session_hours * 3600)
    return token


def read_session(token):
    """Return the user id for a live session and extend its idle window, or None."""
    if not token or len(token) > 128:
        return None
    digest = token_digest(token)
    client = get_redis()
    raw = client.get(_session_key(digest))
    if raw is None:
        return None
    session = json.loads(raw)
    ttl = _remaining_ttl(session["createdAt"])
    if ttl <= 0:
        delete_session(token)
        return None
    client.expire(_session_key(digest), ttl)
    return session["userId"]


def delete_session(token):
    if not token or len(token) > 128:
        return
    digest = token_digest(token)
    client = get_redis()
    raw = client.get(_session_key(digest))
    client.delete(_session_key(digest))
    if raw is not None:
        client.srem(_user_key(json.loads(raw)["userId"]), digest)


def delete_user_sessions(user_id):
    """End every session for an account immediately."""
    client = get_redis()
    digests = client.smembers(_user_key(user_id))
    for digest in digests:
        client.delete(_session_key(digest.decode() if isinstance(digest, bytes) else digest))
    client.delete(_user_key(user_id))


def create_ws_ticket(user_id):
    """A short-lived, single-use credential for opening one WebSocket."""
    ticket = secrets.token_urlsafe(32)
    get_redis().set(_ticket_key(token_digest(ticket)), user_id, ex=get_settings().ws_ticket_seconds)
    return ticket


def consume_ws_ticket(ticket):
    if not ticket or len(ticket) > 128:
        return None
    value = get_redis().getdel(_ticket_key(token_digest(ticket)))
    return value.decode() if isinstance(value, bytes) else value
