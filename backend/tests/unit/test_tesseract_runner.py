"""Unit tests for the Tesseract OCR adapter's process handling and TSV parsing edge cases."""
from types import SimpleNamespace

import pytest

from app.adapters import ocr_tesseract
from app.adapters.ocr_tesseract import TesseractOCR, parse_tesseract_tsv
from app.core.config import get_settings

HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
WORD = "5\t1\t1\t1\t1\t1\t10\t20\t30\t40\t96.5\tHello\n"


@pytest.fixture
def which(monkeypatch):
    monkeypatch.setattr(get_settings(), "tesseract_command", "tesseract")
    monkeypatch.setattr(ocr_tesseract.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")


@pytest.mark.unit
def test_missing_binary_reports_ocr_unavailable(monkeypatch):
    monkeypatch.setattr(ocr_tesseract.shutil, "which", lambda cmd: None)
    monkeypatch.setattr(ocr_tesseract.subprocess, "run", lambda *a, **k: pytest.fail("must not run"))
    with pytest.raises(ValueError, match="ocr_unavailable"):
        TesseractOCR().recognize(b"png", "eng", 1)


@pytest.mark.unit
def test_nonzero_exit_reports_ocr_failed(monkeypatch, which):
    monkeypatch.setattr(ocr_tesseract.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stdout=b"", stderr=b"Error opening data file"))
    with pytest.raises(ValueError, match="ocr_failed"):
        TesseractOCR().recognize(b"png", "eng", 1)


@pytest.mark.unit
def test_runs_tesseract_over_pipes_with_bounded_resources(monkeypatch, which):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=(HEADER + WORD).encode(), stderr=b"")

    monkeypatch.setattr(ocr_tesseract.subprocess, "run", run)
    result = TesseractOCR().recognize(b"png-bytes", "eng+hin", 3)

    args, kwargs = calls[0]
    assert args == ["/usr/bin/tesseract", "stdin", "stdout", "-l", "eng+hin", "--psm", "3", "tsv"]
    assert kwargs["input"] == b"png-bytes"
    assert kwargs["timeout"] == 60
    assert kwargs["capture_output"] is True
    assert kwargs["env"]["OMP_THREAD_LIMIT"] == "1"
    assert result.text == "Hello"
    assert result.regions[0].page == 3
    assert (result.regions[0].left, result.regions[0].top, result.regions[0].confidence) == (10, 20, 96.5)


@pytest.mark.unit
def test_invalid_utf8_output_is_replaced_not_fatal(monkeypatch, which):
    tsv = HEADER.encode() + b"5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t90\tna\xffve\n"
    monkeypatch.setattr(ocr_tesseract.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout=tsv, stderr=b""))
    assert TesseractOCR().recognize(b"png", "eng", 1).text == "na�ve"


@pytest.mark.parametrize("row", [
    "5\t1\t1\t1\t1\t1\t10\t20\t30\t40\tnot-a-number\tBadConf\n",
    "5\t1\tx\t1\t1\t1\t10\t20\t30\t40\t90\tBadBlock\n",
    "5\t1\t1\t1\t1\t1\tleft\t20\t30\t40\t90\tBadBox\n",
    "x\t1\t1\t1\t1\t1\t10\t20\t30\t40\t90\tBadLevel\n",
    "5\t1\t1\t1\t1\t1\t10\t20\t30\n",
    "\n",
])
@pytest.mark.unit
def test_malformed_rows_are_skipped(row):
    result = parse_tesseract_tsv(HEADER + row + WORD, page=1)
    assert result.text == "Hello"
    assert len(result.regions) == 1


@pytest.mark.unit
def test_float_coordinates_are_truncated():
    result = parse_tesseract_tsv(HEADER + "5\t1\t1\t1\t1\t1\t10.7\t20.2\t30.9\t40.0\t90\tFloat\n", page=1)
    region = result.regions[0]
    assert (region.left, region.top, region.width, region.height) == (10, 20, 30, 40)


@pytest.mark.unit
def test_empty_output_gives_empty_result():
    result = parse_tesseract_tsv(HEADER, page=1)
    assert result.text == ""
    assert result.regions == ()


@pytest.mark.unit
def test_paragraphs_in_one_block_become_separate_lines():
    rows = ("5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t90\tFirst\n"
            "5\t1\t1\t2\t1\t1\t0\t0\t1\t1\t90\tSecond\n")
    assert parse_tesseract_tsv(HEADER + rows, page=1).text == "First\nSecond"
