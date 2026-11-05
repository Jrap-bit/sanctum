"""Isolated, bounded page extraction process. Clinical bytes travel over pipes."""
from io import BytesIO
from contextlib import closing
import json
import math
import os
import shutil
import subprocess
import sys
from PIL import Image, ImageOps
import pypdfium2 as pdfium

MAX_PIXELS = 20_000_000
MAX_TEXT = 100_000


def extract(raw, mime, number, executable, language):
    if mime == 'application/pdf':
        with pdfium.PdfDocument(raw) as pdf:
            with closing(pdf[number - 1]) as page:
                with closing(page.get_textpage()) as textpage:
                    if textpage.count_chars() > MAX_TEXT:
                        raise ValueError('page_text_limit')
                    text = textpage.get_text_range().strip()
                if sum(c.isalnum() for c in text) >= 20:
                    return {'rawText': text, 'method': 'embedded_text', 'unreadable': False}
                width, height = page.get_size()
                if width <= 0 or height <= 0 or not math.isfinite(width * height):
                    raise ValueError('page_size')
                scale = min(200 / 72, math.sqrt(MAX_PIXELS / (width * height)) * .99)
                with closing(page.render(scale=scale)) as bitmap:
                    image = bitmap.to_pil().convert('RGB')
    else:
        with Image.open(BytesIO(raw)) as source:
            if source.width * source.height > MAX_PIXELS:
                raise ValueError('page_size')
            image = ImageOps.exif_transpose(source).convert('RGB')
    try:
        binary = shutil.which(executable)
        if not binary:
            raise ValueError('ocr_unavailable')
        stream = BytesIO(); image.save(stream, format='PNG')
        result = subprocess.run([binary, 'stdin', 'stdout', '-l', language, '--psm', '3'],
                                input=stream.getvalue(), capture_output=True, timeout=60,
                                env={**os.environ, 'OMP_THREAD_LIMIT': '1'})
        if result.returncode:
            raise ValueError('ocr_failed')
        text = result.stdout.decode('utf-8', errors='replace').strip()
        if len(text) > MAX_TEXT:
            raise ValueError('page_text_limit')
        return {'rawText': text, 'method': 'ocr', 'unreadable': not bool(text)}
    finally:
        image.close()


def main():
    try:
        raw = sys.stdin.buffer.read(25 * 1024 * 1024 + 1)
        if len(raw) > 25 * 1024 * 1024: raise ValueError('file_limit')
        result = extract(raw, sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4])
        print(json.dumps(result))
    except subprocess.TimeoutExpired:
        print(json.dumps({'error': 'page_timeout'})); sys.exit(1)
    except ValueError as exc:
        code = str(exc)
        print(json.dumps({'error': code if code in {'ocr_unavailable','ocr_failed','page_text_limit','page_size','file_limit'} else 'extraction_failed'})); sys.exit(1)
    except Exception:
        print(json.dumps({'error': 'extraction_failed'})); sys.exit(1)

if __name__ == '__main__': main()
