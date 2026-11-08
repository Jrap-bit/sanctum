from contextlib import closing
from io import BytesIO
import math
from PIL import Image
from PIL import ImageOps
import pypdfium2 as pdfium

from ..core.config import get_settings


MAX_PIXELS = 20_000_000
MAX_TEXT = 100_000


class PdfiumTextExtractor:
    name = "pdfium"

    def __init__(self):
        self.settings = get_settings()

    def page_count(self, raw: bytes, media_type: str) -> int:
        if media_type == "application/pdf":
            with pdfium.PdfDocument(raw) as pdf:
                return len(pdf)
        return 1

    def embedded_text(self, raw: bytes, media_type: str, page: int) -> str | None:
        if media_type != "application/pdf":
            return None
        with pdfium.PdfDocument(raw) as pdf:
            if page < 1 or page > len(pdf):
                raise ValueError("page_size")
            with closing(pdf[page - 1]) as p:
                with closing(p.get_textpage()) as textpage:
                    if textpage.count_chars() > MAX_TEXT:
                        raise ValueError("page_text_limit")
                    text = textpage.get_text_range().strip()
                if sum(c.isalnum() for c in text) >= 20:
                    return text
                return None

    def render_png(self, raw: bytes, media_type: str, page: int) -> bytes:
        if media_type == "application/pdf":
            with pdfium.PdfDocument(raw) as pdf:
                if page < 1 or page > len(pdf):
                    raise ValueError("page_size")
                with closing(pdf[page - 1]) as p:
                    width, height = p.get_size()
                    if width <= 0 or height <= 0 or not math.isfinite(width * height):
                        raise ValueError("page_size")
                    scale = min(200 / 72, math.sqrt(MAX_PIXELS / (width * height)) * 0.99)
                    with closing(p.render(scale=scale)) as bitmap:
                        image = bitmap.to_pil().convert("RGB")
        else:
            with Image.open(BytesIO(raw)) as source:
                if source.width * source.height > MAX_PIXELS:
                    raise ValueError("page_size")
                image = ImageOps.exif_transpose(source).convert("RGB")
        try:
            stream = BytesIO()
            image.save(stream, format="PNG")
            return stream.getvalue()
        finally:
            image.close()
