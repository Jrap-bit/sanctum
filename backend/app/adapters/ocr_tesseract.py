import csv
import os
import shutil
import subprocess

from .base import OCRResult, Region
from ..core.config import get_settings


MAX_TEXT = 100_000


def parse_tesseract_tsv(tsv_text: str, page: int) -> OCRResult:
    lines = tsv_text.splitlines()
    reader = csv.reader(lines, delimiter="\t", quoting=csv.QUOTE_NONE)
    regions: list[Region] = []
    blocks: dict[int, dict[tuple[int, int], list[str]]] = {}

    for row in reader:
        if not row or len(row) < 11:
            continue
        if row[0] == "level":
            continue
        try:
            level = int(row[0])
        except ValueError:
            continue
        if level != 5:
            continue

        raw_word = row[11] if len(row) > 11 else ""
        word = raw_word.strip()
        if not word:
            continue

        try:
            conf = float(row[10])
        except ValueError:
            continue
        if conf < 0:
            continue

        try:
            block_num = int(row[2])
            par_num = int(row[3])
            line_num = int(row[4])
            left = int(float(row[6]))
            top = int(float(row[7]))
            width = int(float(row[8]))
            height = int(float(row[9]))
        except (ValueError, IndexError):
            continue

        regions.append(
            Region(
                text=word,
                page=page,
                left=left,
                top=top,
                width=width,
                height=height,
                confidence=conf,
            )
        )

        if block_num not in blocks:
            blocks[block_num] = {}
        line_key = (par_num, line_num)
        if line_key not in blocks[block_num]:
            blocks[block_num][line_key] = []
        blocks[block_num][line_key].append(word)

    block_strings = []
    for block_id, line_dict in blocks.items():
        line_strings = [" ".join(words) for words in line_dict.values() if words]
        if line_strings:
            block_strings.append("\n".join(line_strings))
    full_text = "\n\n".join(block_strings)

    if len(full_text) > MAX_TEXT:
        raise ValueError("page_text_limit")

    return OCRResult(text=full_text, regions=tuple(regions))


class TesseractOCR:
    name = "tesseract"

    def __init__(self):
        self.settings = get_settings()

    def recognize(self, png: bytes, language: str, page: int) -> OCRResult:
        binary = shutil.which(self.settings.tesseract_command)
        if not binary:
            raise ValueError("ocr_unavailable")

        env = {**os.environ, "OMP_THREAD_LIMIT": "1"}
        result = subprocess.run(
            [binary, "stdin", "stdout", "-l", language, "--psm", "3", "tsv"],
            input=png,
            capture_output=True,
            timeout=60,
            env=env,
        )
        if result.returncode != 0:
            raise ValueError("ocr_failed")

        tsv_text = result.stdout.decode("utf-8", errors="replace")
        return parse_tesseract_tsv(tsv_text, page)
