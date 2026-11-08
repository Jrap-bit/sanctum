"""Ollama LLM engine adapter."""
from collections.abc import Iterator
import json
import time
import httpx

from ..core.config import get_settings
from .base import ModelInfo
from .llm import base_url


class OllamaEngine:
    name = "ollama"

    @property
    def root_url(self) -> str:
        url = base_url()
        if url.endswith("/v1"):
            url = url[:-3]
        return url.rstrip("/")

    def models(self) -> list[ModelInfo]:
        root = self.root_url
        try:
            with httpx.Client(base_url=root, trust_env=False, timeout=3, follow_redirects=False) as client:
                response = client.get("/api/tags")
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError:
            raise ValueError("model_unavailable") from None

        results = []
        for entry in data.get("models", []):
            if entry.get("size", 0) > 0 and not entry.get("remote_model"):
                results.append(ModelInfo(id=entry["name"], available=True, digest=entry.get("digest")))
        return results

    def stream_json(self, model: str, messages: list[dict], schema: dict, max_tokens: int) -> Iterator[str]:
        root = self.root_url
        settings = get_settings()
        deadline = time.monotonic() + settings.llm_timeout_seconds
        payload = {
            "model": model,
            "stream": True,
            "think": False,
            "format": schema,
            "messages": messages,
            "options": {
                "temperature": 0,
                "num_ctx": 16384,
                "num_predict": max_tokens,
            },
            "keep_alive": "5m",
        }

        try:
            with httpx.Client(
                base_url=root,
                trust_env=False,
                follow_redirects=False,
                timeout=settings.llm_timeout_seconds,
            ) as client:
                with client.stream("POST", "/api/chat", json=payload) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if time.monotonic() > deadline:
                            raise ValueError("model_unavailable")
                        if not line:
                            continue
                        try:
                            item = json.loads(line)
                        except Exception:
                            continue
                        if item.get("done_reason") == "length":
                            raise ValueError("incomplete_generation")
                        content = item.get("message", {}).get("content")
                        if content:
                            yield content
                        if item.get("done"):
                            break
        except httpx.HTTPError:
            raise ValueError("model_unavailable") from None
