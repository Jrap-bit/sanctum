"""Isolated, bounded page extraction process. Clinical bytes travel over pipes."""
import json
import subprocess
import sys

from ..core.config import get_settings
from .registry import ocr_engines, text_extractors


def extract(raw: bytes, mime: str, page: int) -> dict:
    settings = get_settings()
    extractor = text_extractors.create(settings.text_extractor)
    embedded = extractor.embedded_text(raw, mime, page)
    if embedded is not None:
        return {
            "rawText": embedded,
            "method": "embedded_text",
            "unreadable": False,
            "regions": [],
        }

    png = extractor.render_png(raw, mime, page)
    ocr = ocr_engines.create(settings.ocr_engine)
    result = ocr.recognize(png, settings.ocr_language, page)
    text = result.text
    regions = [
        {
            "text": r.text,
            "page": r.page,
            "left": r.left,
            "top": r.top,
            "width": r.width,
            "height": r.height,
            "confidence": r.confidence,
        }
        for r in result.regions
    ]
    return {
        "rawText": text,
        "method": "ocr",
        "unreadable": not bool(text.strip()),
        "regions": regions,
    }


def main():
    try:
        raw = sys.stdin.buffer.read(25 * 1024 * 1024 + 1)
        if len(raw) > 25 * 1024 * 1024:
            raise ValueError("file_limit")
        result = extract(raw, sys.argv[1], int(sys.argv[2]))
        print(json.dumps(result))
    except subprocess.TimeoutExpired:
        print(json.dumps({"error": "page_timeout"}))
        sys.exit(1)
    except ValueError as exc:
        code = str(exc)
        print(
            json.dumps(
                {
                    "error": (
                        code
                        if code
                        in {
                            "ocr_unavailable",
                            "ocr_failed",
                            "page_text_limit",
                            "page_size",
                            "file_limit",
                        }
                        else "extraction_failed"
                    )
                }
            )
        )
        sys.exit(1)
    except Exception:
        print(json.dumps({"error": "extraction_failed"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
