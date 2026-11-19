import fakeredis
import pytest

from app.adapters import llm
from app.core import cache


@pytest.fixture(autouse=True)
def redis_client():
    client = fakeredis.FakeRedis()
    cache.set_client(client)
    yield client
    cache.set_client(None)


@pytest.fixture(autouse=True)
def fresh_llm_engine():
    """The LLM engine is cached per process; never let one test's engine leak into the next."""
    llm.reset_engine()
    yield
    llm.reset_engine()


TEST_KINDS = {"unit", "integration"}


def pytest_collection_modifyitems(config, items):
    """Each test carries exactly one of @pytest.mark.unit / @pytest.mark.integration, matching its folder."""
    problems = []
    for item in items:
        kinds = TEST_KINDS & {m.name for m in item.iter_markers()}
        folder = item.path.parent.name
        if len(kinds) != 1:
            problems.append(f"{item.nodeid}: needs exactly one of @pytest.mark.unit or @pytest.mark.integration")
        elif folder in TEST_KINDS and kinds != {folder}:
            problems.append(f"{item.nodeid}: is marked {kinds.pop()} but lives in tests/{folder}/")
    if problems:
        raise pytest.UsageError("Test tagging problems:\n  " + "\n  ".join(problems))
