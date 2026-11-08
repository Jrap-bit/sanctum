"""Sanctum Evaluation Harness (§9.10).

Evaluates OCR and local LLM performance against synthetic clinical records and fixtures.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import platform
import sys
import time
from typing import Any, Sequence

# Ensure backend/ is in sys.path when run directly or imported
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Required imports as specified in the evaluation harness contract
from app.adapters import llm, registry
from app.core.config import get_settings


# ---------------------------------------------------------------------------
# Metric Functions: Levenshtein, CER, WER, Normalisation, Quantiles, Recall
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    """Normalize text by converting to lowercase and collapsing all whitespace."""
    if not text:
        return ""
    return " ".join(text.lower().split())


def levenshtein_distance(seq1: Sequence[Any], seq2: Sequence[Any]) -> int:
    """Compute Levenshtein edit distance between two sequences (chars or tokens)."""
    if seq1 == seq2:
        return 0
    if not seq1:
        return len(seq2)
    if not seq2:
        return len(seq1)

    if len(seq1) < len(seq2):
        seq1, seq2 = seq2, seq1

    prev_row = list(range(len(seq2) + 1))
    for i, item1 in enumerate(seq1):
        curr_row = [i + 1] * (len(seq2) + 1)
        for j, item2 in enumerate(seq2):
            cost = 0 if item1 == item2 else 1
            curr_row[j + 1] = min(
                curr_row[j] + 1,       # insertion
                prev_row[j + 1] + 1,   # deletion
                prev_row[j] + cost,    # substitution
            )
        prev_row = curr_row
    return prev_row[len(seq2)]


def compute_cer(reference: str, hypothesis: str, normalize: bool = False) -> float:
    """
    Compute Character Error Rate (CER = edit distance / reference length).
    If reference is empty: returns 0.0 if hypothesis is empty, else 1.0.
    """
    if normalize:
        reference = normalize_text(reference)
        hypothesis = normalize_text(hypothesis)

    if not reference:
        return 0.0 if not hypothesis else 1.0

    dist = levenshtein_distance(reference, hypothesis)
    return dist / len(reference)


def compute_wer(reference: str, hypothesis: str, normalize: bool = False) -> float:
    """
    Compute Word Error Rate (WER = word edits / reference words).
    If reference words are empty: returns 0.0 if hypothesis is empty, else 1.0.
    """
    if normalize:
        ref_words = normalize_text(reference).split()
        hyp_words = normalize_text(hypothesis).split()
    else:
        ref_words = reference.split()
        hyp_words = hypothesis.split()

    if not ref_words:
        return 0.0 if not hyp_words else 1.0

    dist = levenshtein_distance(ref_words, hyp_words)
    return dist / len(ref_words)


def percentile(data: list[float], p: float) -> float:
    """Calculate the p-th percentile (0 <= p <= 100) using linear interpolation."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    if len(sorted_data) == 1:
        return float(sorted_data[0])

    k = (len(sorted_data) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_data) - 1)
    d = k - f
    return sorted_data[f] + (sorted_data[c] - sorted_data[f]) * d


def p50(data: list[float]) -> float:
    """Median / 50th percentile."""
    return percentile(data, 50.0)


def p95(data: list[float]) -> float:
    """95th percentile."""
    return percentile(data, 95.0)


def compute_phrase_recall(required_phrases: list[str], output_text: str) -> float:
    """
    Compute automated phrase recall (case-insensitive).
    An empty output scores zero recall, not a pass.
    """
    if not required_phrases:
        return 1.0
    if not output_text or not output_text.strip():
        return 0.0

    text_lower = output_text.lower()
    matched = sum(1 for phrase in required_phrases if phrase.lower() in text_lower)
    return matched / len(required_phrases)


def count_forbidden_phrases(forbidden_phrases: list[str], output_text: str) -> int:
    """Count forbidden phrases found in output_text (case-insensitive)."""
    if not forbidden_phrases or not output_text or not output_text.strip():
        return 0

    text_lower = output_text.lower()
    return sum(1 for phrase in forbidden_phrases if phrase.lower() in text_lower)


# ---------------------------------------------------------------------------
# OCR Evaluation Runner
# ---------------------------------------------------------------------------

def run_ocr_eval(
    ocr_cases: list[dict],
    fixtures_dir: Path | None = None,
) -> dict[str, Any]:
    """Run OCR evaluation using in-process TesseractOCR and PdfiumTextExtractor."""
    from app.adapters.ocr_tesseract import TesseractOCR
    from app.adapters.text_pdfium import PdfiumTextExtractor

    settings = get_settings()
    extractor = PdfiumTextExtractor()
    ocr = TesseractOCR()

    page_results = []
    latencies: list[float] = []
    raw_cers: list[float] = []
    norm_cers: list[float] = []
    raw_wers: list[float] = []
    norm_wers: list[float] = []
    successful_count = 0

    for case in ocr_cases:
        cid = case["id"]
        ground_truth = case["ground_truth"]
        variant = case.get("variant", "unknown")
        raw_bytes = case["image_bytes"]

        t0 = time.perf_counter()
        try:
            png = extractor.render_png(raw_bytes, "image/png", 1)
            result = ocr.recognize(png, settings.ocr_language, 1)
            latency = time.perf_counter() - t0
            latencies.append(latency)

            pred_text = result.text
            rcer = compute_cer(ground_truth, pred_text, normalize=False)
            ncer = compute_cer(ground_truth, pred_text, normalize=True)
            rwer = compute_wer(ground_truth, pred_text, normalize=False)
            nwer = compute_wer(ground_truth, pred_text, normalize=True)

            raw_cers.append(rcer)
            norm_cers.append(ncer)
            raw_wers.append(rwer)
            norm_wers.append(nwer)
            successful_count += 1

            page_results.append({
                "id": cid,
                "variant": variant,
                "latency_seconds": round(latency, 4),
                "raw_cer": round(rcer, 4),
                "norm_cer": round(ncer, 4),
                "raw_wer": round(rwer, 4),
                "norm_wer": round(nwer, 4),
                "success": True,
                "error": None,
            })
        except Exception as exc:
            latency = time.perf_counter() - t0
            latencies.append(latency)
            # An exception is a recorded failure and counts against coverage, never dropped.
            raw_cers.append(1.0)
            norm_cers.append(1.0)
            raw_wers.append(1.0)
            norm_wers.append(1.0)

            page_results.append({
                "id": cid,
                "variant": variant,
                "latency_seconds": round(latency, 4),
                "raw_cer": 1.0,
                "norm_cer": 1.0,
                "raw_wer": 1.0,
                "norm_wer": 1.0,
                "success": False,
                "error": str(exc),
            })

    total_pages = len(ocr_cases)
    coverage = successful_count / total_pages if total_pages > 0 else 0.0

    median_summary = {
        "median_latency_seconds": round(p50(latencies), 4) if latencies else 0.0,
        "median_raw_cer": round(p50(raw_cers), 4) if raw_cers else 1.0,
        "median_norm_cer": round(p50(norm_cers), 4) if norm_cers else 1.0,
        "median_raw_wer": round(p50(raw_wers), 4) if raw_wers else 1.0,
        "median_norm_wer": round(p50(norm_wers), 4) if norm_wers else 1.0,
        "coverage": round(coverage, 4),
        "total_pages": total_pages,
        "successful_pages": successful_count,
    }

    # Handwritten evaluation fixtures
    handwritten_results = None
    if fixtures_dir and fixtures_dir.is_dir():
        hw_cases = []
        for png_file in sorted(fixtures_dir.glob("*.png")):
            txt_file = png_file.with_suffix(".txt")
            if txt_file.is_file():
                hw_cases.append({
                    "id": png_file.stem,
                    "variant": "handwritten",
                    "ground_truth": txt_file.read_text(encoding="utf-8"),
                    "image_bytes": png_file.read_bytes(),
                })
        if hw_cases:
            handwritten_results = run_ocr_eval(hw_cases, fixtures_dir=None)

    return {
        "pages": page_results,
        "median": median_summary,
        "handwritten": handwritten_results,
    }


# ---------------------------------------------------------------------------
# LLM Evaluation Runner
# ---------------------------------------------------------------------------

def run_llm_eval(
    llm_cases: list[dict],
    models: list[str],
) -> dict[str, Any]:
    """
    Run serialized LLM evaluation across specified models.
    Builds source dict shaped like app.services.summaries::snapshot.
    """
    model_evals = {}

    for model in models:
        latencies: list[float] = []
        successful_count = 0
        total_facts = 0
        total_required_matched = 0
        total_required_count = 0
        total_forbidden_matched = 0

        failure_counts = {
            "unsupported_evidence": 0,
            "invalid_generation": 0,
            "incomplete_generation": 0,
            "model_unavailable": 0,
        }

        for case in llm_cases:
            case_id = str(case["id"])
            text = case["text"]
            # Snapshot dictionary layout from app.services.summaries::snapshot
            source = {
                "id": case_id,
                "version": 1,
                "type": "session",
                "title": "Finalized session",
                "eventDate": "2026-01-01",
                "dateStatus": "known",
                "href": f"/patients/eval/sessions/{case_id}",
                "text": text,
                "wordCount": len(text.split()),
                "byteCount": len(text.encode("utf-8")),
            }
            sources = [source]

            required = case.get("required", [])
            forbidden = case.get("forbidden", [])
            total_required_count += len(required)

            t0 = time.perf_counter()
            try:
                result = llm.generate(sources, "single_session", model=model)
                latency = time.perf_counter() - t0
                latencies.append(latency)
                successful_count += 1

                paragraphs = result.get("paragraphs", [])
                facts = result.get("facts", [])
                total_facts += len(facts)

                # Extract text for phrase checks
                summary_text = " ".join(p.get("text", "") for p in paragraphs)
                if not summary_text.strip() and facts:
                    summary_text = " ".join(f.get("text", "") for f in facts)

                if summary_text.strip():
                    text_lower = summary_text.lower()
                    total_required_matched += sum(1 for phrase in required if phrase.lower() in text_lower)
                    total_forbidden_matched += count_forbidden_phrases(forbidden, summary_text)

            except Exception as exc:
                latency = time.perf_counter() - t0
                latencies.append(latency)
                err_code = str(exc)
                if err_code in failure_counts:
                    failure_counts[err_code] += 1
                else:
                    failure_counts["model_unavailable"] += 1
                # Failed cases are retained: empty output scores zero recall

        total_cases = len(llm_cases)
        success_rate = successful_count / total_cases if total_cases > 0 else 0.0
        req_recall = (
            total_required_matched / total_required_count
            if total_required_count > 0
            else 0.0
        )

        model_evals[model] = {
            "model": model,
            "latency_p50_seconds": round(p50(latencies), 4) if latencies else 0.0,
            "latency_p95_seconds": round(p95(latencies), 4) if latencies else 0.0,
            "success_rate": round(success_rate, 4),
            "required_phrase_recall": round(req_recall, 4),
            "forbidden_phrase_count": total_forbidden_matched,
            "facts_proposed": total_facts,
            "failure_counts": failure_counts,
        }

    return model_evals


# ---------------------------------------------------------------------------
# Report Formatting (Markdown & JSON)
# ---------------------------------------------------------------------------

def generate_markdown_report(
    run_date: str,
    host_info: str,
    model_digests: dict[str, str],
    ocr_results: dict[str, Any],
    llm_results: dict[str, Any],
) -> str:
    """Generate evaluation.md content adhering to §9.10 specifications."""
    lines: list[str] = [
        "# Sanctum Evaluation Report (§9.10)",
        "",
        f"- **Run Date:** {run_date}",
        f"- **Host Platform:** {host_info}",
        f"- **Python Version:** {platform.python_version()}",
        "",
        "## Model Digests",
        "",
    ]

    for model_name, digest in model_digests.items():
        lines.append(f"- **{model_name}:** `{digest}`")

    lines.extend([
        "",
        "## OCR Evaluation",
        "",
        "| Page ID | Variant | Latency (s) | Raw CER | Norm CER | Raw WER | Norm WER | Status |",
        "|---|---|---|---|---|---|---|---|",
    ])

    for page in ocr_results.get("pages", []):
        status_str = "pass" if page["success"] else f"fail ({page['error']})"
        lines.append(
            f"| {page['id']} | {page['variant']} | {page['latency_seconds']:.4f} | "
            f"{page['raw_cer']:.4f} | {page['norm_cer']:.4f} | {page['raw_wer']:.4f} | "
            f"{page['norm_wer']:.4f} | {status_str} |"
        )

    median = ocr_results.get("median", {})
    lines.extend([
        "",
        "### OCR Summary (Median)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Median Latency | {median.get('median_latency_seconds', 0.0):.4f}s |",
        f"| Median Raw CER | {median.get('median_raw_cer', 1.0):.4f} |",
        f"| Median Norm CER | {median.get('median_norm_cer', 1.0):.4f} |",
        f"| Median Raw WER | {median.get('median_raw_wer', 1.0):.4f} |",
        f"| Median Norm WER | {median.get('median_norm_wer', 1.0):.4f} |",
        f"| Page Coverage | {median.get('coverage', 0.0) * 100:.1f}% ({median.get('successful_pages', 0)}/{median.get('total_pages', 0)}) |",
        "",
        "### Handwritten OCR",
        "",
    ])

    hw = ocr_results.get("handwritten")
    if hw is None:
        lines.append("handwritten: not measured")
    else:
        lines.extend([
            "| Page ID | Latency (s) | Raw CER | Norm CER | Raw WER | Norm WER | Status |",
            "|---|---|---|---|---|---|---|",
        ])
        for page in hw.get("pages", []):
            status_str = "pass" if page["success"] else f"fail ({page['error']})"
            lines.append(
                f"| {page['id']} | {page['latency_seconds']:.4f} | {page['raw_cer']:.4f} | "
                f"{page['norm_cer']:.4f} | {page['raw_wer']:.4f} | {page['norm_wer']:.4f} | {status_str} |"
            )

    lines.extend([
        "",
        "## LLM Evaluation: Model Comparison",
        "",
        "> Note: The phrase check is an automated phrase proxy, not the two-annotator factual-support study in §9.9.",
        "",
        "| Model | Latency p50 (s) | Latency p95 (s) | Success Rate | Required Recall | Forbidden Count | Facts Proposed | Errors (unsupported / invalid / incomplete / unavailable) |",
        "|---|---|---|---|---|---|---|---|",
    ])

    for model_name, mdata in llm_results.items():
        fc = mdata["failure_counts"]
        errors_str = f"{fc.get('unsupported_evidence', 0)} / {fc.get('invalid_generation', 0)} / {fc.get('incomplete_generation', 0)} / {fc.get('model_unavailable', 0)}"
        lines.append(
            f"| {model_name} | {mdata['latency_p50_seconds']:.4f} | {mdata['latency_p95_seconds']:.4f} | "
            f"{mdata['success_rate'] * 100:.1f}% | {mdata['required_phrase_recall'] * 100:.1f}% | "
            f"{mdata['forbidden_phrase_count']} | {mdata['facts_proposed']} | {errors_str} |"
        )

    lines.extend([
        "",
        "## Limitations",
        "",
        "- **Sample Size:** The evaluation is conducted on a small sample size consisting of 6 generated synthetic pages and 5 synthetic clinical cases.",
        "- **Synthetic Pages & Handwriting (NFR-17):** The test pages are typed and synthetic, so handwriting accuracy (NFR-17) is not measured unless handwritten fixtures were supplied.",
        "- **Proxy Targets (NFR-16):** NFR-16's 95%/85% targets are not established by this proxy. The phrase check is an automated phrase proxy, not the two-annotator factual-support study in §9.9.",
        "- **Clinical Disclaimer:** No result produced by this evaluation harness is a claim of clinical validity or endorsement for direct patient care.",
        "",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Sanctum Evaluation Harness (§9.10)")
    parser.add_argument(
        "--models",
        type=str,
        default=None,
        help="Comma-separated models to evaluate (default: settings.llm_models)",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="../docs/evidence",
        help="Output directory for results.json and evaluation.md",
    )
    args = parser.parse_args()

    settings = get_settings()
    if args.models:
        selected_models = [m.strip() for m in args.models.split(",") if m.strip()]
    else:
        selected_models = list(settings.llm_models)

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    from cases import LLM_CASES, get_ocr_cases

    # 1. Gather model digests from llm.status()
    model_digests: dict[str, str] = {}
    try:
        stat = llm.status()
        lookup = {m["id"]: m.get("digest") or "unavailable" for m in stat.get("models", [])}
        for m in selected_models:
            model_digests[m] = lookup.get(m, "unavailable")
    except Exception:
        for m in selected_models:
            model_digests[m] = "unavailable"

    # 2. Run OCR section
    ocr_cases = get_ocr_cases()
    fixtures_dir = REPO_ROOT / "evaluation" / "fixtures" / "handwritten"
    ocr_results = run_ocr_eval(ocr_cases, fixtures_dir=fixtures_dir)

    # 3. Run LLM section
    llm_results = run_llm_eval(LLM_CASES, selected_models)

    # 4. Generate outputs
    run_date = datetime.now(timezone.utc).isoformat()
    host_info = f"{platform.system()} {platform.release()} ({platform.machine()})"

    report_markdown = generate_markdown_report(
        run_date=run_date,
        host_info=host_info,
        model_digests=model_digests,
        ocr_results=ocr_results,
        llm_results=llm_results,
    )

    combined_results = {
        "run_date": run_date,
        "host_platform": host_info,
        "python_version": platform.python_version(),
        "model_digests": model_digests,
        "ocr": ocr_results,
        "llm": llm_results,
        "limitations": {
            "sample_size": "6 generated pages, 5 cases",
            "handwriting_accuracy": "pages are typed and synthetic so handwriting accuracy (NFR-17) is not measured unless handwritten fixtures were supplied",
            "proxy_targets": "NFR-16's 95%/85% targets are not established by this proxy; automated phrase proxy, not the two-annotator factual-support study in §9.9",
            "clinical_validity": "no result is a claim of clinical validity",
        },
    }

    (out_dir / "results.json").write_text(json.dumps(combined_results, indent=2), encoding="utf-8")
    (out_dir / "evaluation.md").write_text(report_markdown, encoding="utf-8")


if __name__ == "__main__":
    main()
