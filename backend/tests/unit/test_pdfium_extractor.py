"""Unit tests for the pdfium text extractor: page counts, embedded text and page rendering."""
from io import BytesIO

import pytest
from fpdf import FPDF
from PIL import Image

from app.adapters import text_pdfium
from app.adapters.text_pdfium import PdfiumTextExtractor

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
LONG_TEXT = "The patient described improved sleep over the last two weeks."


def make_pdf(*pages):
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    for text in pages:
        pdf.add_page()
        if text:
            pdf.multi_cell(0, 8, text)
    return bytes(pdf.output())


def make_image(size=(40, 20), mode="RGB", fmt="PNG", exif=None):
    stream = BytesIO()
    image = Image.new(mode, size, "white")
    if exif is not None:
        image.save(stream, format=fmt, exif=exif)
    else:
        image.save(stream, format=fmt)
    return stream.getvalue()


def png_size(data):
    with Image.open(BytesIO(data)) as image:
        return image.size, image.mode


@pytest.fixture
def extractor():
    return PdfiumTextExtractor()


@pytest.mark.unit
def test_page_count_for_pdf_and_image(extractor):
    assert extractor.page_count(make_pdf("one", "two", "three"), "application/pdf") == 3
    assert extractor.page_count(make_image(), "image/png") == 1


@pytest.mark.unit
def test_embedded_text_returned_when_page_has_enough_text(extractor):
    raw = make_pdf(LONG_TEXT, "")
    assert "improved sleep" in extractor.embedded_text(raw, "application/pdf", 1)


@pytest.mark.parametrize("text", ["", "Hi 123", "a b c d e f g h i j k l m n o p q r s"])
@pytest.mark.unit
def test_embedded_text_none_when_fewer_than_20_alphanumerics(extractor, text):
    assert extractor.embedded_text(make_pdf(text), "application/pdf", 1) is None


@pytest.mark.unit
def test_embedded_text_none_for_images(extractor):
    assert extractor.embedded_text(make_image(), "image/png", 1) is None


@pytest.mark.parametrize("page", [0, -1, 3])
@pytest.mark.unit
def test_embedded_text_rejects_out_of_range_pages(extractor, page):
    with pytest.raises(ValueError, match="page_size"):
        extractor.embedded_text(make_pdf(LONG_TEXT, LONG_TEXT), "application/pdf", page)


@pytest.mark.unit
def test_embedded_text_enforces_character_limit(extractor, monkeypatch):
    monkeypatch.setattr(text_pdfium, "MAX_TEXT", 10)
    with pytest.raises(ValueError, match="page_text_limit"):
        extractor.embedded_text(make_pdf(LONG_TEXT), "application/pdf", 1)


@pytest.mark.unit
def test_render_pdf_page_at_200_dpi(extractor):
    data = extractor.render_png(make_pdf(LONG_TEXT), "application/pdf", 1)
    assert data.startswith(PNG_SIGNATURE)
    (width, height), mode = png_size(data)
    # A4 is 595.28 x 841.89 points; 200 dpi is a scale of 200/72.
    assert abs(width - 595.28 * 200 / 72) <= 2
    assert abs(height - 841.89 * 200 / 72) <= 2
    assert mode == "RGB"


@pytest.mark.unit
def test_render_pdf_page_scales_down_to_pixel_budget(extractor, monkeypatch):
    monkeypatch.setattr(text_pdfium, "MAX_PIXELS", 100_000)
    (width, height), _ = png_size(extractor.render_png(make_pdf(LONG_TEXT), "application/pdf", 1))
    assert width * height <= 100_000


@pytest.mark.parametrize("page", [0, 2])
@pytest.mark.unit
def test_render_pdf_rejects_out_of_range_pages(extractor, page):
    with pytest.raises(ValueError, match="page_size"):
        extractor.render_png(make_pdf(LONG_TEXT), "application/pdf", page)


@pytest.mark.unit
def test_render_image_converts_to_rgb_png(extractor):
    data = extractor.render_png(make_image(mode="RGBA"), "image/png", 1)
    assert data.startswith(PNG_SIGNATURE)
    assert png_size(data) == ((40, 20), "RGB")


@pytest.mark.unit
def test_render_image_applies_exif_orientation(extractor):
    exif = Image.Exif()
    exif[0x0112] = 6  # Rotated 90 degrees: width and height swap after transposing.
    raw = make_image(size=(40, 20), fmt="JPEG", exif=exif)
    assert png_size(extractor.render_png(raw, "image/jpeg", 1))[0] == (20, 40)


@pytest.mark.unit
def test_render_image_rejects_oversized_images(extractor, monkeypatch):
    monkeypatch.setattr(text_pdfium, "MAX_PIXELS", 100)
    with pytest.raises(ValueError, match="page_size"):
        extractor.render_png(make_image(size=(20, 20)), "image/png", 1)
