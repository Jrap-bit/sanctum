"""Render an inert PNG for original-page comparison without serving active PDFs inline."""
from PIL import Image
from PIL import ImageOps
from contextlib import closing
from fastapi import HTTPException
from io import BytesIO
from pathlib import Path
import math
import os
import pypdfium2 as pdfium
import signal
import subprocess
import sys



def render(raw, mime, number):
    if mime == 'application/pdf':
        with pdfium.PdfDocument(raw) as pdf:
            with closing(pdf[number - 1]) as page:
                w,h = page.get_size()
                if w <= 0 or h <= 0 or not math.isfinite(w*h): raise ValueError('Invalid size')
                scale=min(150/72, math.sqrt(8_000_000/(w*h))*.99)
                with closing(page.render(scale=scale)) as bitmap: image=bitmap.to_pil().convert('RGB')
    else:
        with Image.open(BytesIO(raw)) as source:
            if source.width*source.height > 20_000_000: raise ValueError('Invalid size')
            image=ImageOps.exif_transpose(source).convert('RGB')
            image.thumbnail((2400,2400))
    try:
        result=BytesIO();image.save(result, format='PNG');return result.getvalue()
    finally: image.close()


def render_isolated(raw, mime, number):
    process=subprocess.Popen([sys.executable,'-m','app.adapters.preview_page',mime,str(number)],stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=Path(__file__).resolve().parents[2],start_new_session=True)
    try: result,_=process.communicate(raw,timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid,signal.SIGKILL);process.communicate()
        raise HTTPException(503,'Page preview timed out. Download the original for comparison.') from None
    if process.returncode or not result.startswith(b'\x89PNG\r\n\x1a\n'):
        raise HTTPException(503,'Page preview is unavailable. Download the original for comparison.')
    return result


if __name__ == '__main__':
    try:
        raw=sys.stdin.buffer.read(25*1024*1024+1)
        if len(raw)>25*1024*1024: raise ValueError('Too large')
        sys.stdout.buffer.write(render(raw,sys.argv[1],int(sys.argv[2])))
    except Exception: sys.exit(1)
