"""Unit tests for model status reporting and the end-to-end generate() pipeline with stub engines."""
import json

import pytest

from app.adapters import llm as ai
from app.adapters.base import ModelInfo
from app.adapters.llm_fake import FakeEngine
from app.core.config import get_settings

TEXT = "The patient denied alcohol use. Sleep improved this week."


def source(text=TEXT, **overrides):
    return {"id": "note-1", "title": "Session", "href": "/patients/p/sessions/note-1", "version": 2,
            "eventDate": "2026-11-01", "dateStatus": "exact", "wordCount": len(text.split()),
            "text": text, **overrides}


class StubEngine:
    name = "stub"

    def __init__(self, models=None, fragments=(), error=None):
        self._models = models if models is not None else [ModelInfo("qwen3:4b", True, "sha256:abc")]
        self.fragments = fragments
        self.error = error
        self.requests = []

    def models(self):
        if self.error:
            raise self.error
        return self._models

    def stream_json(self, model, messages, schema, max_tokens):
        self.requests.append((model, messages, schema, max_tokens))
        yield from self.fragments


@pytest.fixture
def use_engine(monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_models", ["qwen3:4b", "llama3.2:3b"])
    monkeypatch.setattr(get_settings(), "summary_model", "qwen3:4b")

    def install(engine):
        monkeypatch.setattr(ai, "_engine", engine)
        return engine
    return install


@pytest.mark.unit
def test_status_healthy_reports_digest_and_catalog(use_engine):
    use_engine(StubEngine())
    result = ai.status()
    assert result["state"] == "healthy"
    assert result["model"] == "qwen3:4b"
    assert result["digest"] == "sha256:abc"
    assert result["models"] == [{"id": "qwen3:4b", "available": True, "digest": "sha256:abc"},
                                {"id": "llama3.2:3b", "available": False, "digest": None}]
    assert (result["maxSources"], result["maxWords"], result["maxSourceBytes"]) == (30, 2000, 8000)


@pytest.mark.unit
def test_status_digest_unknown_when_runtime_omits_it(use_engine):
    use_engine(StubEngine(models=[ModelInfo("qwen3:4b", True, None)]))
    assert ai.status()["digest"] == "unknown"


@pytest.mark.parametrize("models", [[], [ModelInfo("qwen3:4b", False, None)]])
@pytest.mark.unit
def test_status_model_missing(use_engine, models):
    use_engine(StubEngine(models=models))
    assert ai.status()["state"] == "model_missing"


@pytest.mark.unit
def test_status_unavailable_when_runtime_fails(use_engine):
    use_engine(StubEngine(error=ConnectionError("refused")))
    result = ai.status("llama3.2:3b")
    assert result["state"] == "unavailable"
    assert result["model"] == "llama3.2:3b"
    assert all(not m["available"] for m in result["models"])


@pytest.mark.unit
def test_generate_with_fake_engine_streams_and_grounds(use_engine):
    use_engine(FakeEngine())
    deltas = []
    result = ai.generate([source()], "single_session", on_delta=deltas.append)
    assert "".join(deltas) == "The patient denied alcohol use."
    assert result["paragraphs"][0]["evidence"][0]["passage"] == "The patient denied alcohol use."
    assert result["paragraphs"][0]["evidence"][0]["sourceVersion"] == 2
    assert result["facts"][0]["label"] == "observation"
    assert result["model"] == "qwen3:4b"
    assert result["modelDigest"] == "unavailable"
    assert result["promptVersion"] == ai.PROMPT_VERSION


def selection(passage="P1"):
    return json.dumps({"summary": [{"text": "Alcohol use was denied.",
                                    "evidence": [{"sourceId": "S1", "passageId": passage}]}], "facts": []})


@pytest.mark.unit
def test_generate_passes_request_to_engine_and_records_digest(use_engine):
    payload = selection()
    engine = use_engine(StubEngine(fragments=[payload[:10], payload[10:]]))
    result = ai.generate([source()], "single_session")
    model, messages, schema, max_tokens = engine.requests[0]
    assert model == "qwen3:4b"
    assert messages[0]["role"] == "system"
    assert json.loads(messages[1]["content"])["sourceRecords"][0]["passages"]["P1"] == "The patient denied alcohol use."
    assert schema == ai.SelectedGeneration.model_json_schema()
    assert max_tokens == get_settings().llm_max_output_tokens
    assert result["modelDigest"] == "sha256:abc"


@pytest.mark.unit
def test_generate_uses_requested_model(use_engine):
    engine = use_engine(StubEngine(models=[ModelInfo("llama3.2:3b", True, "d")], fragments=[selection()]))
    assert ai.generate([source()], "single_session", model="llama3.2:3b")["model"] == "llama3.2:3b"
    assert engine.requests[0][0] == "llama3.2:3b"


@pytest.mark.unit
def test_generate_rejects_models_outside_catalog(use_engine):
    engine = use_engine(StubEngine(models=[ModelInfo("other", True)]))
    with pytest.raises(ValueError, match="model_unavailable"):
        ai.generate([source()], "single_session", model="other")
    assert engine.requests == []


@pytest.mark.unit
def test_generate_rejects_unhealthy_model(use_engine):
    engine = use_engine(StubEngine(models=[]))
    with pytest.raises(ValueError, match="model_unavailable"):
        ai.generate([source()], "single_session")
    assert engine.requests == []


@pytest.mark.unit
def test_generate_checks_size_before_contacting_engine(use_engine):
    engine = use_engine(StubEngine(error=AssertionError("must not be called")))
    with pytest.raises(ValueError, match="source_limit"):
        ai.generate([source(wordCount=2001)], "single_session")
    assert engine.requests == []


@pytest.mark.parametrize("fragments", [["{not json"], ['{"summary": []}'], [""]])
@pytest.mark.unit
def test_generate_rejects_malformed_output(use_engine, fragments):
    use_engine(StubEngine(fragments=fragments))
    with pytest.raises(ValueError, match="invalid_generation"):
        ai.generate([source()], "single_session")


@pytest.mark.unit
def test_generate_rejects_invented_passage(use_engine):
    use_engine(StubEngine(fragments=[selection("P9")]))
    with pytest.raises(ValueError, match="unsupported_evidence"):
        ai.generate([source()], "single_session")


@pytest.mark.unit
def test_engine_built_once_from_settings(monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_engine", "fake")
    monkeypatch.setattr(ai, "_engine", None)
    first = ai.engine()
    assert isinstance(first, FakeEngine)
    assert ai.engine() is first
    ai.reset_engine()
    assert ai._engine is None
