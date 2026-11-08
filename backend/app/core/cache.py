"""Redis: sessions, rate limits, job progress and short-lived artifacts. Never a store of record."""
import json

import redis

from .config import get_settings

_client = None


def get_redis():
    global _client
    if _client is None:
        _client = redis.Redis.from_url(get_settings().redis_url, socket_timeout=5, socket_connect_timeout=5)
    return _client


def set_client(client):
    """Replace the connection; used by tests."""
    global _client
    _client = client


MAINTENANCE_KEY = "sanctum:maintenance"


def set_maintenance(active):
    client = get_redis()
    if active:
        client.set(MAINTENANCE_KEY, "1", ex=3600)
    else:
        client.delete(MAINTENANCE_KEY)


def in_maintenance():
    try:
        return bool(get_redis().exists(MAINTENANCE_KEY))
    except redis.RedisError:
        return False


def job_channel(job_id):
    return f"job:{job_id}:events"


def job_state_key(job_id):
    return f"job:{job_id}:state"


def publish_progress(job_id, *, state, progress=None, stage=None, message=None, delta=None):
    """Report job progress. Advisory: a Redis outage must never fail the job (NFR-09)."""
    event = {"jobId": str(job_id), "state": state, "progress": progress, "stage": stage, "message": message}
    try:
        client = get_redis()
        # Only the live channel carries partial model text; the retained state never does.
        client.set(job_state_key(job_id), json.dumps(event), ex=get_settings().raw_text_ttl_seconds)
        client.publish(job_channel(job_id), json.dumps({**event, "delta": delta}))
    except redis.RedisError:
        pass


def read_job_state(job_id):
    try:
        value = get_redis().get(job_state_key(job_id))
    except redis.RedisError:
        return None
    return json.loads(value) if value else None
