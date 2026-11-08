"""Interfaces each replaceable adapter implements. Domain code depends only on these (ADR-04)."""
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Region:
    text: str
    page: int
    left: int
    top: int
    width: int
    height: int
    confidence: float | None = None  # Provider-reported; never treated as calibrated accuracy.


@dataclass(frozen=True)
class OCRResult:
    text: str
    regions: tuple[Region, ...] = ()


@dataclass(frozen=True)
class ModelInfo:
    id: str
    available: bool
    digest: str | None = None


class TextExtractor(Protocol):
    name: str

    def page_count(self, raw: bytes, media_type: str) -> int: ...

    def embedded_text(self, raw: bytes, media_type: str, page: int) -> str | None:
        """Return usable embedded text, or None when the page needs OCR."""

    def render_png(self, raw: bytes, media_type: str, page: int) -> bytes: ...


class OCREngine(Protocol):
    name: str

    def recognize(self, png: bytes, language: str, page: int) -> OCRResult: ...


class ObjectStore(Protocol):
    name: str

    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...


class LLMEngine(Protocol):
    name: str

    def models(self) -> list[ModelInfo]: ...

    def stream_json(self, model: str, messages: list[dict], schema: dict, max_tokens: int) -> Iterator[str]:
        """Yield text fragments of one schema-constrained completion."""
