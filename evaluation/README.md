# Sanctum Evaluation Harness (§9.10)

This directory contains the evaluation harness for Sanctum's optical character recognition (OCR) and local large language model (LLM) summary pipeline, as specified in §9.10.

## Overview

The harness evaluates:
1. **OCR Ingestion Performance**: Evaluates text extraction and OCR accuracy using in-process `PdfiumTextExtractor` and `TesseractOCR` adapters on synthetic clinical pages (clean, rotated, noisy, small fonts) and optional handwritten fixtures.
2. **LLM Summary Performance**: Evaluates serial structured clinical record summarization across configured models (`settings.llm_models`), measuring latency percentiles (p50, p95), schema/source grounding success rate, failure categories, automated phrase recall, forbidden unsupported assertions, and proposed fact counts.

## Directory Layout

- `run_eval.py`: Evaluation runner and metric computation engine. Produces `results.json` and `evaluation.md`.
- `cases.py`: Benchmark data definitions containing:
  - Six synthetic OCR pages with ground truth (3 large clean font, 2 noisy with 1-degree rotation via Pillow, 1 small font).
  - Five fixed synthetic clinical LLM cases with required faithful phrases and forbidden unsupported assertions (covering negation, historical timing, and prompt injection).
- `fixtures/handwritten/`: Fixture directory for real handwritten samples. Any `.png` file with a sibling `.txt` ground truth is evaluated and reported under handwritten OCR. If empty, handwritten evaluation reports `handwritten: not measured`.
- `backend/tests/test_evaluation_metrics.py`: Unit test suite verifying metric calculation (CER, WER, normalisation, empty references, p50/p95, phrase recall).

## Running the Evaluation

To execute the full evaluation harness against configured models:

```bash
cd backend && .venv313/bin/python ../evaluation/run_eval.py [--models model1,model2] [--out ../docs/evidence]
```

### Options:
- `--models`: Comma-separated list of model names to benchmark. Defaults to `settings.llm_models`.
- `--out`: Output directory for generated artifacts (`results.json` and `evaluation.md`). Defaults to `../docs/evidence`.

## Running the Unit Tests

The metric functions (CER, WER, normalisation, empty reference handling, latency percentiles, and phrase recall) are tested via pytest:

```bash
cd backend && .venv313/bin/python -m pytest tests/test_evaluation_metrics.py -q
```

## Metrics & Reporting

### OCR Metrics
- **Levenshtein Distance**: Standard dynamic programming edit distance for both character sequences and word token sequences.
- **CER (Character Error Rate)**: Character edit distance divided by reference length. Reported in both raw and normalised (lowercase, collapsed whitespace) form.
- **WER (Word Error Rate)**: Word substitutions + deletions + insertions divided by reference word count. Reported in raw and normalised form.
- **Coverage & Latency**: Processing latency per page, median latency, and page coverage (failures count against coverage and are never dropped).

### LLM Metrics
- **Latency Percentiles**: Serial generation latency p50 and p95 across cases.
- **Success Rate**: Proportion of cases completing with valid schema and source passage grounding.
- **Failure Categorization**: Failure counts mapped to error codes:
  - `unsupported_evidence`: Uncited or ungrounded claims failing source passage verification.
  - `invalid_generation`: Output schema violations or invalid JSON.
  - `incomplete_generation`: Model token budget exhausted before completion.
  - `model_unavailable`: Model missing, timeout, or backend engine offline.
- **Automated Phrase Proxy**: Case-insensitive recall of required faithful phrases (empty output scores zero recall, not a pass) and count of forbidden unsupported assertions.
- **Facts Proposed**: Total clinical facts proposed for separate clinician review.

## Limitations & Disclaimers

1. **Sample Size**: The automated harness runs on 6 synthetic pages and 5 clinical cases designed for continuous integration verification.
2. **Handwriting (NFR-17)**: The primary pages are synthetic and typed; handwriting accuracy (NFR-17) is not measured unless handwritten fixtures are supplied.
3. **Benchmark Targets (NFR-16)**: NFR-16's 95%/85% targets are not established by this proxy. The phrase check is an automated phrase proxy, not the two-annotator factual-support study in §9.9.
4. **Clinical Disclaimer**: No result from this evaluation harness constitutes a claim of clinical validity or fitness for medical decision-making.
