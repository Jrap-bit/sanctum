"""Unit tests for the inert page preview renderer and its isolated subprocess wrapper."""
from io import BytesIO
import subprocess

import pytest
from fastapi import HTTPException
from fpdf import FPDF
from PIL import Image

from app.adapters import preview_page

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def make_pdf(pages=1):
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    for number in range(pages):
        pdf.add_page()
        pdf.cell(0, 10, f"Synthetic page {number + 1}")
    return bytes(pdf.output())


def make_png(size, mode="RGB"):
    stream = BytesIO()
    Image.new(mode, size).save(stream, format="PNG")
    return stream.getvalue()


def size_of(data):
    with Image.open(BytesIO(data)) as image:
        return image.size


@pytest.mark.unit
def test_render_pdf_page_at_150_dpi():
    data = preview_page.render(make_pdf(2), "application/pdf", 2)
    assert data.startswith(PNG_SIGNATURE)
    width, height = size_of(data)
    assert abs(width - 595.28 * 150 / 72) <= 2
    assert abs(height - 841.89 * 150 / 72) <= 2


@pytest.mark.unit
def test_render_image_is_thumbnailed_to_2400_pixels():
    assert size_of(preview_page.render(make_png((3000, 1000)), "image/png", 1)) == (2400, 800)


@pytest.mark.unit
def test_render_small_image_keeps_its_size():
    assert size_of(preview_page.render(make_png((30, 10), "RGBA"), "image/png", 1)) == (30, 10)


@pytest.mark.unit
def test_render_rejects_images_over_20_megapixels():
    huge = make_png((5000, 4001), mode="1")  # 1-bit keeps the fixture small on disk.
    with pytest.raises(ValueError, match="Invalid size"):
        preview_page.render(huge, "image/png", 1)


@pytest.mark.unit
def test_render_isolated_returns_png_from_subprocess():
    data = preview_page.render_isolated(make_png((16, 16)), "image/png", 1)
    assert data.startswith(PNG_SIGNATURE)
    assert size_of(data) == (16, 16)


@pytest.mark.unit
def test_render_isolated_reports_unavailable_for_corrupt_input():
    with pytest.raises(HTTPException) as exc:
        preview_page.render_isolated(b"not an image", "image/png", 1)
    assert exc.value.status_code == 503
    assert "unavailable" in exc.value.detail


class HangingProcess:
    pid = 4242
    returncode = None

    def __init__(self, *args, **kwargs):
        self.calls = 0

    def communicate(self, data=None, timeout=None):
        self.calls += 1
        if self.calls == 1:
            raise subprocess.TimeoutExpired("preview", timeout)
        return b"", b""


@pytest.mark.unit
def test_render_isolated_kills_process_group_on_timeout(monkeypatch):
    killed = []
    monkeypatch.setattr(preview_page.subprocess, "Popen", HangingProcess)
    monkeypatch.setattr(preview_page.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    with pytest.raises(HTTPException) as exc:
        preview_page.render_isolated(b"raw", "image/png", 1)
    assert exc.value.status_code == 503
    assert "timed out" in exc.value.detail
    assert killed == [(4242, preview_page.signal.SIGKILL)]


@pytest.mark.unit
def test_render_isolated_rejects_successful_exit_without_png(monkeypatch):
    class NotPng(HangingProcess):
        returncode = 0

        def communicate(self, data=None, timeout=None):
            return b"<html>", b""

    monkeypatch.setattr(preview_page.subprocess, "Popen", NotPng)
    with pytest.raises(HTTPException) as exc:
        preview_page.render_isolated(b"raw", "image/png", 1)
    assert exc.value.status_code == 503
