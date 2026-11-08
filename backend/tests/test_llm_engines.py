"""Tests for LLM engines, URL validation, and SummaryTextStream."""
import json
import time
import httpx
import pytest

from app.adapters import llm as ai
from app.adapters.base import ModelInfo
from app.adapters.llm import SummaryTextStream, base_url
from app.adapters.llm_fake import FakeEngine
from app.adapters.llm_ollama import OllamaEngine
from app.adapters.llm_openai import OpenAICompatEngine
from app.core.config import get_settings

real_client = httpx.Client


def patch_client(monkeypatch, transport):
    def client_factory(**kwargs):
        clean_kwargs = {k: v for k, v in kwargs.items() if k != 'transport'}
        return real_client(transport=transport, **clean_kwargs)
    monkeypatch.setattr(httpx, 'Client', client_factory)


def test_base_url_disallowed_host_and_invariants(monkeypatch):
    settings = get_settings()

    # Valid URLs
    monkeypatch.setattr(settings, 'llm_base_url', 'http://127.0.0.1:11434/v1')
    assert base_url() == 'http://127.0.0.1:11434/v1'

    monkeypatch.setattr(settings, 'llm_base_url', 'http://localhost:11434/v1/')
    assert base_url() == 'http://localhost:11434/v1'

    monkeypatch.setattr(settings, 'llm_base_url', 'https://127.0.0.1:11434/v1')
    assert base_url() == 'https://127.0.0.1:11434/v1'

    # Disallowed host
    monkeypatch.setattr(settings, 'llm_base_url', 'http://evil.com:11434/v1')
    with pytest.raises(ValueError, match='local_model_configuration'):
        base_url()

    # Disallowed scheme
    monkeypatch.setattr(settings, 'llm_base_url', 'ftp://127.0.0.1:11434/v1')
    with pytest.raises(ValueError, match='local_model_configuration'):
        base_url()

    # Userinfo present
    monkeypatch.setattr(settings, 'llm_base_url', 'http://user:pass@127.0.0.1:11434/v1')
    with pytest.raises(ValueError, match='local_model_configuration'):
        base_url()

    # Query present
    monkeypatch.setattr(settings, 'llm_base_url', 'http://127.0.0.1:11434/v1?token=123')
    with pytest.raises(ValueError, match='local_model_configuration'):
        base_url()

    # Fragment present
    monkeypatch.setattr(settings, 'llm_base_url', 'http://127.0.0.1:11434/v1#section')
    with pytest.raises(ValueError, match='local_model_configuration'):
        base_url()


def test_disallowed_host_raises_before_any_request(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, 'llm_base_url', 'http://evil.com/v1')

    ollama = OllamaEngine()
    with pytest.raises(ValueError, match='local_model_configuration'):
        ollama.models()

    with pytest.raises(ValueError, match='local_model_configuration'):
        list(ollama.stream_json('qwen3:4b', [], {}, 100))

    openai = OpenAICompatEngine()
    with pytest.raises(ValueError, match='local_model_configuration'):
        openai.models()

    with pytest.raises(ValueError, match='local_model_configuration'):
        list(openai.stream_json('qwen3:4b', [], {}, 100))


def test_ollama_engine_models_and_stream(monkeypatch):
    tags_response = {
        'models': [
            {'name': 'qwen3:4b', 'size': 5000, 'digest': 'sha256:12345'},
            {'name': 'remote_model', 'size': 5000, 'remote_model': True},
            {'name': 'empty_model', 'size': 0},
        ]
    }

    chat_lines = [
        json.dumps({'message': {'content': '{"summary": [{"text": "Patient was examined.", '}, 'done': False}) + '\n',
        json.dumps({'message': {'content': '"evidence": [{"sourceId": "S1", "passageId": "P1"}]}], '}, 'done': False}) + '\n',
        json.dumps({'message': {'content': '"facts": []}'}, 'done': True, 'done_reason': 'stop'}) + '\n',
    ]

    def handler(request: httpx.Request):
        if request.method == 'GET' and request.url.path == '/api/tags':
            return httpx.Response(200, json=tags_response)
        if request.method == 'POST' and request.url.path == '/api/chat':
            return httpx.Response(200, content=''.join(chat_lines).encode('utf-8'))
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    patch_client(monkeypatch, transport)

    engine = OllamaEngine()
    models = engine.models()
    assert models == [ModelInfo(id='qwen3:4b', available=True, digest='sha256:12345')]

    chunks = list(engine.stream_json('qwen3:4b', [{'role': 'user', 'content': 'test'}], {}, 1000))
    assembled = ''.join(chunks)
    assert assembled == '{"summary": [{"text": "Patient was examined.", "evidence": [{"sourceId": "S1", "passageId": "P1"}]}], "facts": []}'
    parsed = ai.SelectedGeneration.model_validate_json(assembled)
    assert parsed.summary[0].text == 'Patient was examined.'


def test_ollama_engine_done_reason_length(monkeypatch):
    chat_lines = [
        json.dumps({'message': {'content': '{"summary": ['}, 'done': False}) + '\n',
        json.dumps({'message': {'content': ''}, 'done': True, 'done_reason': 'length'}) + '\n',
    ]

    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=''.join(chat_lines).encode('utf-8')))
    patch_client(monkeypatch, transport)

    engine = OllamaEngine()
    with pytest.raises(ValueError, match='incomplete_generation'):
        list(engine.stream_json('qwen3:4b', [], {}, 100))


def test_openai_compat_engine_models_and_stream(monkeypatch):
    models_response = {
        'data': [
            {'id': 'qwen3:4b'},
            {'id': 'llama3.2:3b'},
        ]
    }

    sse_lines = [
        'data: {"choices": [{"delta": {"content": "{\\"summary\\": [{\\"text\\": \\"Exam clear.\\", "}, "finish_reason": null}]}\n\n',
        'data: {"choices": [{"delta": {"content": "\\"evidence\\": [{\\"sourceId\\": \\"S1\\", \\"passageId\\": \\"P1\\"}]}], \\"facts\\": []}"}, "finish_reason": null}]}\n\n',
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n',
        'data: [DONE]\n\n',
    ]

    def handler(request: httpx.Request):
        assert request.headers.get('Authorization') == 'Bearer local'
        if request.method == 'GET' and request.url.path == '/v1/models':
            return httpx.Response(200, json=models_response)
        if request.method == 'POST' and request.url.path == '/v1/chat/completions':
            return httpx.Response(200, content=''.join(sse_lines).encode('utf-8'))
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    patch_client(monkeypatch, transport)

    engine = OpenAICompatEngine()
    models = engine.models()
    assert models == [
        ModelInfo(id='qwen3:4b', available=True, digest=None),
        ModelInfo(id='llama3.2:3b', available=True, digest=None),
    ]

    chunks = list(engine.stream_json('qwen3:4b', [{'role': 'user', 'content': 'test'}], {}, 1000))
    assembled = ''.join(chunks)
    assert assembled == '{"summary": [{"text": "Exam clear.", "evidence": [{"sourceId": "S1", "passageId": "P1"}]}], "facts": []}'
    parsed = ai.SelectedGeneration.model_validate_json(assembled)
    assert parsed.summary[0].text == 'Exam clear.'


def test_openai_compat_engine_finish_reason_length(monkeypatch):
    sse_lines = [
        'data: {"choices": [{"delta": {"content": "{\\"summary\\": "}, "finish_reason": null}]}\n\n',
        'data: {"choices": [{"delta": {}, "finish_reason": "length"}]}\n\n',
    ]

    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=''.join(sse_lines).encode('utf-8')))
    patch_client(monkeypatch, transport)

    engine = OpenAICompatEngine()
    with pytest.raises(ValueError, match='incomplete_generation'):
        list(engine.stream_json('qwen3:4b', [], {}, 100))


def test_openai_compat_requires_v1_path(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, 'llm_base_url', 'http://127.0.0.1:11434')
    engine = OpenAICompatEngine()
    with pytest.raises(ValueError, match='local_model_configuration'):
        engine.models()


def test_total_deadline_enforced(monkeypatch):
    settings = get_settings()
    chat_lines = [
        json.dumps({'message': {'content': 'chunk1'}, 'done': False}) + '\n',
        json.dumps({'message': {'content': 'chunk2'}, 'done': False}) + '\n',
    ]

    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=''.join(chat_lines).encode('utf-8')))
    patch_client(monkeypatch, transport)

    current_time = 1000.0
    def mock_monotonic():
        nonlocal current_time
        val = current_time
        current_time += settings.llm_timeout_seconds + 10
        return val

    monkeypatch.setattr(time, 'monotonic', mock_monotonic)

    engine = OllamaEngine()
    with pytest.raises(ValueError, match='model_unavailable'):
        list(engine.stream_json('qwen3:4b', [], {}, 100))


def test_fake_engine_output_validates():
    engine = FakeEngine()
    settings = get_settings()
    models = engine.models()
    assert [m.id for m in models] == settings.llm_models
    assert all(m.available for m in models)

    user_msg = json.dumps({'sourceRecords': [{'sourceId': 'S1', 'passages': {'P1': 'The patient denied alcohol use.'}}]})
    messages = [{'role': 'user', 'content': user_msg}]
    chunks = list(engine.stream_json('qwen3:4b', messages, {}, 1000))
    assert len(chunks) > 1

    assembled = ''.join(chunks)
    parsed = ai.SelectedGeneration.model_validate_json(assembled)
    assert parsed.summary[0].text == 'The patient denied alcohol use.'
    assert parsed.summary[0].evidence[0].sourceId == 'S1'
    assert parsed.summary[0].evidence[0].passageId == 'P1'

    # Test with resolve_passages and grounded
    source = {'id': 'src-1', 'version': 1, 'title': 'Session 1', 'href': '/s1', 'text': 'The patient denied alcohol use.'}
    grounded_res = ai.resolve_passages(parsed, [source])
    assert grounded_res['paragraphs'][0]['text'] == 'The patient denied alcohol use.'


def test_summary_text_stream_decoded_text_and_fragments():
    stream = SummaryTextStream()

    fragments = [
        '{"sum',
        'mary": [{"te',
        'xt": "First paragraph with quote: \\"Hello\\".\\',
        'nSecond line of first paragraph with char \\u00',
        '41.", "evidence": [{"sourceId": "S1", "passageId": "P1"}]}, {"text": "Second paragraph text.", "evidence": []}], ',
        '"fa',
        'cts": [{"text": "THIS MUST NOT BE EMITTED", "label": "concern"}]}',
    ]

    emitted = []
    for frag in fragments:
        chunk = stream.feed(frag)
        if chunk:
            emitted.append(chunk)

    full_output = ''.join(emitted)

    expected = 'First paragraph with quote: "Hello".\nSecond line of first paragraph with char A.\n\nSecond paragraph text.'
    assert full_output == expected
    assert 'THIS MUST NOT BE EMITTED' not in full_output
    assert 'facts' not in full_output


def test_engine_http_error_mapped_to_model_unavailable(monkeypatch):
    def failing_handler(req: httpx.Request):
        return httpx.Response(503)

    transport = httpx.MockTransport(failing_handler)
    patch_client(monkeypatch, transport)

    ollama = OllamaEngine()
    with pytest.raises(ValueError, match='model_unavailable'):
        ollama.models()
    with pytest.raises(ValueError, match='model_unavailable'):
        list(ollama.stream_json('qwen3:4b', [], {}, 100))

    openai = OpenAICompatEngine()
    with pytest.raises(ValueError, match='model_unavailable'):
        openai.models()
    with pytest.raises(ValueError, match='model_unavailable'):
        list(openai.stream_json('qwen3:4b', [], {}, 100))
