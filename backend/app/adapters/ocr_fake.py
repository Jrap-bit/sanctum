from .base import OCRResult
from ..core.config import get_settings


class FakeOCR:
    name = "fake"

    def __init__(self):
        self.settings = get_settings()

    def recognize(self, png: bytes, language: str, page: int) -> OCRResult:
        return OCRResult(text=f"Synthetic OCR text for page {page}.")
