"""Unit tests for Redis rate limits and progressive login delays."""
import pytest

from app.core.security import token_digest
from app.services import rate_limits


def block_ttl(redis_client, scope, value):
    return redis_client.ttl(f"rl:block:{token_digest(f'{scope}:{value}')}")


@pytest.mark.unit
def test_consume_allows_up_to_limit_then_refuses(redis_client):
    assert [rate_limits.consume("reset", "alice", 3, 60) for _ in range(5)] == [True, True, True, False, False]
    key = f"rl:counter:{token_digest('reset:alice')}"
    assert 0 < redis_client.ttl(key) <= 60


@pytest.mark.unit
def test_consume_counts_scopes_and_values_separately():
    assert rate_limits.consume("reset", "alice", 1)
    assert rate_limits.consume("reset", "bob", 1)
    assert rate_limits.consume("login", "alice", 1)
    assert not rate_limits.consume("reset", "alice", 1)


@pytest.mark.unit
def test_consume_restores_missing_window(redis_client):
    rate_limits.consume("reset", "alice", 5, 60)
    key = f"rl:counter:{token_digest('reset:alice')}"
    redis_client.persist(key)
    rate_limits.consume("reset", "alice", 5, 60)
    assert 0 < redis_client.ttl(key) <= 60


@pytest.mark.unit
def test_no_block_below_threshold(redis_client):
    for _ in range(4):
        rate_limits.record_failure("login", "alice")
    assert rate_limits.retry_after("login", "alice") == 0
    assert 0 < redis_client.ttl(f"rl:failures:{token_digest('login:alice')}") <= 900


@pytest.mark.unit
def test_delay_doubles_from_threshold(redis_client):
    delays = []
    for _ in range(8):
        rate_limits.record_failure("login", "alice")
        delays.append(block_ttl(redis_client, "login", "alice"))
    assert delays[:4] == [-2, -2, -2, -2]  # -2: no block key yet.
    assert delays[4:] == [1, 2, 4, 8]
    assert rate_limits.retry_after("login", "alice") == 8


@pytest.mark.unit
def test_delay_is_capped_at_15_minutes(redis_client):
    redis_client.set(f"rl:failures:{token_digest('login:alice')}", 30)
    rate_limits.record_failure("login", "alice")
    assert block_ttl(redis_client, "login", "alice") == 900


@pytest.mark.unit
def test_custom_threshold(redis_client):
    rate_limits.record_failure("activation", "token", threshold=1)
    assert rate_limits.retry_after("activation", "token") == 1


@pytest.mark.unit
def test_clear_failures_removes_counter_and_block(redis_client):
    for _ in range(6):
        rate_limits.record_failure("login", "alice")
    rate_limits.clear_failures("login", "alice")
    assert rate_limits.retry_after("login", "alice") == 0
    assert redis_client.keys("rl:*") == []


@pytest.mark.unit
def test_keys_never_contain_the_raw_identifier(redis_client):
    rate_limits.record_failure("login", "alice@example.test", threshold=1)
    rate_limits.consume("reset", "alice@example.test", 1)
    keys = [k.decode() for k in redis_client.keys("rl:*")]
    assert keys and not any("alice" in k for k in keys)
