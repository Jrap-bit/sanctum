"""Unit tests for Redis helpers: maintenance flag and advisory job progress."""
import json

import pytest
import redis

from app.core import cache
from app.core.config import get_settings


class BrokenRedis:
    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise redis.ConnectionError("down")
        return fail


@pytest.mark.unit
def test_get_redis_connects_lazily_once(monkeypatch):
    built = []
    sentinel = object()
    monkeypatch.setattr(redis.Redis, "from_url", lambda url, **kw: built.append((url, kw)) or sentinel)
    cache.set_client(None)
    assert cache.get_redis() is sentinel
    assert cache.get_redis() is sentinel
    assert built == [(get_settings().redis_url, {"socket_timeout": 5, "socket_connect_timeout": 5})]


@pytest.mark.unit
def test_maintenance_flag_round_trip(redis_client):
    assert not cache.in_maintenance()
    cache.set_maintenance(True)
    assert cache.in_maintenance()
    assert 0 < redis_client.ttl(cache.MAINTENANCE_KEY) <= 3600
    cache.set_maintenance(False)
    assert not cache.in_maintenance()


@pytest.mark.unit
def test_maintenance_reads_as_off_when_redis_is_down():
    cache.set_client(BrokenRedis())
    assert cache.in_maintenance() is False


@pytest.mark.unit
def test_job_keys_are_namespaced_per_job():
    assert cache.job_channel("abc") == "job:abc:events"
    assert cache.job_state_key("abc") == "job:abc:state"


@pytest.mark.unit
def test_publish_progress_retains_state_without_partial_text(redis_client):
    pubsub = redis_client.pubsub()
    pubsub.subscribe(cache.job_channel("j1"))
    assert pubsub.get_message(timeout=1)["type"] == "subscribe"

    cache.publish_progress("j1", state="running", progress=40, stage="summary", delta="The patient")

    expected = {"jobId": "j1", "state": "running", "progress": 40, "stage": "summary", "message": None}
    assert cache.read_job_state("j1") == expected
    assert "The patient" not in redis_client.get(cache.job_state_key("j1")).decode()
    assert 0 < redis_client.ttl(cache.job_state_key("j1")) <= get_settings().raw_text_ttl_seconds

    live = pubsub.get_message(timeout=1)
    assert json.loads(live["data"]) == {**expected, "delta": "The patient"}


@pytest.mark.unit
def test_read_job_state_missing_returns_none():
    assert cache.read_job_state("unknown") is None


@pytest.mark.unit
def test_progress_is_advisory_when_redis_is_down():
    cache.set_client(BrokenRedis())
    cache.publish_progress("j1", state="failed")  # Must not raise.
    assert cache.read_job_state("j1") is None
