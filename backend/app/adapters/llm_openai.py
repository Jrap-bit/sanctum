"""OpenAI-compatible LLM engine adapter."""
from collections.abc import Iterator
import json
import time
import httpx

from ..core.config import get_settings
from .base import ModelInfo
from .llm import base_url


class OpenAICompatEngine:
    name = "openai_compat"

    @property
    def root_url(self) -> str:
        url = base_url()
        if not url.endswith("/v1"):
            raise ValueError("local_model_configuration")
        return url

    def models(self) -> list[ModelInfo]:
        root = self.root_url
        settings = get_settings()
        headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
        try:
            with httpx.Client(
                base_url=root,
                trust_env=False,
                timeout=3,
                follow_redirects=False,
                headers=headers,
            ) as client:
                response = client.get("/models")
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError:
            raise ValueError("model_unavailable") from None

        items = data.get("data", []) if isinstance(data, dict) else data
        return [ModelInfo(id=item["id"], available=True, digest=None) for item in items]

    def stream_json(self, model: str, messages: list[dict], schema: dict, max_tokens: int) -> Iterator[str]:
        root = self.root_url
        settings = get_settings()
        deadline = time.monotonic() + settings.llm_timeout_seconds
        headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "summary",
                    "schema": schema,
                    "strict": True,
                },
            },
        }

        try:
            with httpx.Client(
                base_url=root,
                trust_env=False,
                follow_redirects=False,
                timeout=settings.llm_timeout_seconds,
                headers=headers,
            ) as client:
                with client.stream("POST", "/chat/completions", json=payload) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if time.monotonic() > deadline:
                            raise ValueError("model_unavailable")
                        if not line:
                            continue
                        line_str = line.strip()
                        if line_str.startswith("data:"):
                            raw = line_str[5:].strip()
                            if raw == "[DONE]":
                                break
                            try:
                                item = json.loads(raw)
                            except Exception:
                                continue
                            choices = item.get("choices", [])
                            if choices:
                                choice = choices[0]
                                if choice.get("finish_reason") == "length":
                                    raise ValueError("incomplete_generation")
                                delta = choice.get("delta", {})
                                content = delta.get("content")
                                if content:
                                    yield content
        except httpx.HTTPError:
            raise ValueError("model_unavailable") from None
