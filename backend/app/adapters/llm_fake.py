"""Fake LLM engine for testing."""
from collections.abc import Iterator
import json

from ..core.config import get_settings
from .base import ModelInfo


class FakeEngine:
    name = "fake"

    def models(self) -> list[ModelInfo]:
        settings = get_settings()
        return [ModelInfo(id=m, available=True, digest=None) for m in settings.llm_models]

    def stream_json(self, model: str, messages: list[dict], schema: dict, max_tokens: int) -> Iterator[str]:
        text = "The patient denied alcohol use."
        for msg in reversed(messages):
            if msg.get("role") == "user":
                try:
                    user_data = json.loads(msg.get("content", ""))
                    records = user_data.get("sourceRecords", [])
                    if records and "passages" in records[0]:
                        record_passages = records[0]["passages"]
                        if "P1" in record_passages:
                            text = record_passages["P1"]
                            break
                except Exception:
                    pass

        payload = {
            "summary": [
                {
                    "text": text,
                    "evidence": [{"sourceId": "S1", "passageId": "P1"}],
                }
            ],
            "facts": [
                {
                    "text": text,
                    "evidence": [{"sourceId": "S1", "passageId": "P1"}],
                    "label": "observation",
                    "assertion": "present",
                    "temporality": "current",
                    "subject": "patient",
                }
            ],
        }
        serialized = json.dumps(payload)
        chunk_size = 20
        for i in range(0, len(serialized), chunk_size):
            yield serialized[i : i + chunk_size]
