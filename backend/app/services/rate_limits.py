"""Redis-backed rate limiting and progressive delays. No database use."""
from ..core.cache import get_redis
from ..core.security import token_digest


def retry_after(scope: str, value: str, threshold: int = 5) -> int:
    client = get_redis()
    digest = token_digest(f"{scope}:{value}")
    ttl = client.ttl(f"rl:block:{digest}")
    return max(0, ttl) if ttl and ttl > 0 else 0


def record_failure(scope: str, value: str, threshold: int = 5) -> None:
    client = get_redis()
    digest = token_digest(f"{scope}:{value}")
    key = f"rl:failures:{digest}"
    count = client.incr(key)
    if count == 1 or client.ttl(key) == -1:
        client.expire(key, 900)
    if count >= threshold:
        delay = min(2 ** (count - threshold), 900)
        client.set(f"rl:block:{digest}", "1", ex=delay)


def clear_failures(scope: str, value: str) -> None:
    client = get_redis()
    digest = token_digest(f"{scope}:{value}")
    client.delete(f"rl:failures:{digest}", f"rl:block:{digest}")


def consume(scope: str, value: str, limit: int, window_seconds: int = 900) -> bool:
    client = get_redis()
    digest = token_digest(f"{scope}:{value}")
    key = f"rl:counter:{digest}"
    count = client.incr(key)
    if count == 1 or client.ttl(key) == -1:
        client.expire(key, window_seconds)
    return count <= limit
