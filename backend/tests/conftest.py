import fakeredis
import pytest

from app.core import cache


@pytest.fixture(autouse=True)
def redis_client():
    client = fakeredis.FakeRedis()
    cache.set_client(client)
    yield client
    cache.set_client(None)
