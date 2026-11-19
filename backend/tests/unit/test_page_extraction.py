"""Unit tests for the isolated page extraction entry point (embedded text vs OCR, error codes)."""
from io import BytesIO
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.adapters import extract_page
from app.adapters.base import OCRResult, Region


class StubExtractor:
    def __init__(self, embedded=None):
        self.embedded = embedded
        self.rendered = []

    def embedded_text(self, raw, mime, page):
        return self.embedded

    def render_png(self, raw, mime, page):
        self.rendered.append((raw, mime, page))
        return b"png-bytes"


class StubOCR:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def recognize(self, png, language, page):
        self.calls.append((png, language, page))
        return self.result


@pytest.fixture
def stubs(monkeypatch):
    holder = SimpleNamespace(extractor=StubExtractor(), ocr=StubOCR(OCRResult(text="")))
    monkeypatch.setattr(extract_page.text_extractors, "create", lambda name: holder.extractor)
    monkeypatch.setattr(extract_page.ocr_engines, "create", lambda name: holder.ocr)
    return holder


@pytest.mark.unit
def test_embedded_text_skips_rendering_and_ocr(stubs):
    stubs.extractor.embedded = "Typed note with embedded text."
    result = extract_page.extract(b"%PDF", "application/pdf", 1)
    assert result == {"rawText": "Typed note with embedded text.", "method": "embedded_text",
                      "unreadable": False, "regions": []}
    assert stubs.extractor.rendered == []
    assert stubs.ocr.calls == []


@pytest.mark.unit
def test_ocr_path_renders_page_and_maps_regions(stubs):
    region = Region(text="Worried", page=2, left=1, top=2, width=3, height=4, confidence=91.5)
    stubs.ocr.result = OCRResult(text="Worried", regions=(region,))
    result = extract_page.extract(b"raw", "image/png", 2)
    assert stubs.extractor.rendered == [(b"raw", "image/png", 2)]
    assert stubs.ocr.calls == [(b"png-bytes", "eng", 2)]
    assert result["method"] == "ocr"
    assert result["unreadable"] is False
    assert result["regions"] == [{"text": "Worried", "page": 2, "left": 1, "top": 2,
                                  "width": 3, "height": 4, "confidence": 91.5}]


@pytest.mark.parametrize("text", ["", "   \n\t"])
@pytest.mark.unit
def test_blank_ocr_text_is_marked_unreadable(stubs, text):
    stubs.ocr.result = OCRResult(text=text)
    assert extract_page.extract(b"raw", "image/png", 1)["unreadable"] is True


def run_main(monkeypatch, capsys, raw=b"raw", argv=("extract_page", "image/png", "1")):
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=BytesIO(raw)))
    monkeypatch.setattr(sys, "argv", list(argv))
    code = 0
    try:
        extract_page.main()
    except SystemExit as exc:
        code = exc.code
    return code, json.loads(capsys.readouterr().out)


@pytest.mark.unit
def test_main_prints_result_json(monkeypatch, capsys):
    monkeypatch.setattr(extract_page, "extract", lambda raw, mime, page: {"rawText": f"{mime}:{page}:{raw.decode()}"})
    assert run_main(monkeypatch, capsys) == (0, {"rawText": "image/png:1:raw"})


@pytest.mark.parametrize("error", ["ocr_unavailable", "ocr_failed", "page_text_limit", "page_size", "file_limit"])
@pytest.mark.unit
def test_main_passes_known_error_codes_through(monkeypatch, capsys, error):
    def fail(*args):
        raise ValueError(error)
    monkeypatch.setattr(extract_page, "extract", fail)
    assert run_main(monkeypatch, capsys) == (1, {"error": error})


@pytest.mark.parametrize("exc", [ValueError("secret patient text"), RuntimeError("boom"), ValueError()])
@pytest.mark.unit
def test_main_hides_unexpected_errors(monkeypatch, capsys, exc):
    def fail(*args):
        raise exc
    monkeypatch.setattr(extract_page, "extract", fail)
    assert run_main(monkeypatch, capsys) == (1, {"error": "extraction_failed"})


@pytest.mark.unit
def test_main_reports_ocr_timeout(monkeypatch, capsys):
    def fail(*args):
        raise subprocess.TimeoutExpired("tesseract", 60)
    monkeypatch.setattr(extract_page, "extract", fail)
    assert run_main(monkeypatch, capsys) == (1, {"error": "page_timeout"})


@pytest.mark.unit
def test_main_rejects_input_over_25_mib(monkeypatch, capsys):
    monkeypatch.setattr(extract_page, "extract", lambda *a: pytest.fail("must not extract"))
    raw = b"x" * (25 * 1024 * 1024 + 1)
    assert run_main(monkeypatch, capsys, raw=raw) == (1, {"error": "file_limit"})
