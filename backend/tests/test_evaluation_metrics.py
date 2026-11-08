"""Unit tests for the evaluation harness metrics and cases (§9.10)."""
from pathlib import Path
import sys

# Ensure evaluation directory is in sys.path
EVAL_DIR = Path(__file__).resolve().parents[2] / "evaluation"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

import pytest
from run_eval import (
    compute_cer,
    compute_phrase_recall,
    compute_wer,
    count_forbidden_phrases,
    levenshtein_distance,
    normalize_text,
    p50,
    p95,
    percentile,
)


def test_normalize_text():
    # Lowercase conversion
    assert normalize_text("Patient John Doe") == "patient john doe"

    # Whitespace collapsing: spaces, tabs, newlines
    assert normalize_text("  vital   signs:  \n  120/80\t mmHg \n") == "vital signs: 120/80 mmhg"

    # Empty and whitespace-only strings
    assert normalize_text("") == ""
    assert normalize_text("   \t \n  ") == ""


def test_levenshtein_distance():
    # Identical
    assert levenshtein_distance("", "") == 0
    assert levenshtein_distance("hello", "hello") == 0
    assert levenshtein_distance(["a", "b"], ["a", "b"]) == 0

    # Insertions, deletions, substitutions on strings
    assert levenshtein_distance("kitten", "sitting") == 3
    assert levenshtein_distance("", "test") == 4
    assert levenshtein_distance("test", "") == 4

    # Sequence of tokens / words
    assert levenshtein_distance(["the", "quick", "fox"], ["the", "brown", "fox"]) == 1
    assert levenshtein_distance(["a", "b"], []) == 2
    assert levenshtein_distance([], ["x", "y", "z"]) == 3


def test_compute_cer():
    # Exact match
    assert compute_cer("clinical note", "clinical note") == 0.0

    # Raw vs normalized CER
    ref = "Blood Pressure 120/80"
    hyp = "blood pressure 120/80"
    # Raw has case differences (B, P)
    assert compute_cer(ref, hyp, normalize=False) > 0.0
    # Normalized collapses case and whitespace
    assert compute_cer(ref, hyp, normalize=True) == 0.0

    # Specific edit rate
    # Reference length 4, 1 substitution -> 0.25
    assert compute_cer("card", "cord") == 0.25


def test_compute_wer():
    # Exact match
    assert compute_wer("the patient reports headache", "the patient reports headache") == 0.0

    # Raw vs normalized WER
    ref = "The Patient\nReports   Headache"
    hyp = "the patient reports headache"
    assert compute_wer(ref, hyp, normalize=False) > 0.0
    assert compute_wer(ref, hyp, normalize=True) == 0.0

    # Substitutions + deletions + insertions
    # 4 reference words, 1 word substituted -> 1/4 = 0.25
    assert compute_wer("the patient denies pain", "the patient reports pain") == 0.25
    # 3 reference words, 1 insertion -> 1/3
    assert compute_wer("patient denies pain", "the patient denies pain") == 1 / 3


def test_empty_reference_handling():
    # CER empty reference
    assert compute_cer("", "") == 0.0
    assert compute_cer("", "non-empty hypothesis") == 1.0
    assert compute_cer("non-empty reference", "") == 1.0

    # WER empty reference
    assert compute_wer("", "") == 0.0
    assert compute_wer("", "some output text") == 1.0
    assert compute_wer("some reference text", "") == 1.0


def test_percentiles_p50_p95():
    # Empty list handling
    assert percentile([], 50) == 0.0
    assert p50([]) == 0.0
    assert p95([]) == 0.0

    # Single value list
    assert p50([4.2]) == 4.2
    assert p95([4.2]) == 4.2

    # Odd count median
    assert p50([10.0, 20.0, 30.0]) == 20.0

    # Even count median
    assert p50([10.0, 20.0, 30.0, 40.0]) == 25.0

    # Distribution p95
    data = list(range(1, 101))  # 1 to 100
    assert p50(data) == 50.5
    assert p95(data) == pytest.approx(95.05, rel=1e-3)


def test_compute_phrase_recall():
    required = ["generalized anxiety", "deep breathing", "two weeks"]

    # Full recall (case-insensitive)
    full_output = "The patient practiced DEEP BREATHING for Generalized Anxiety. Follow-up in two weeks."
    assert compute_phrase_recall(required, full_output) == 1.0

    # Partial recall (2 of 3)
    partial_output = "The patient practiced deep breathing. Follow-up in two weeks."
    assert compute_phrase_recall(required, partial_output) == pytest.approx(2 / 3)

    # Zero recall (none found)
    zero_output = "Routine physical wellness examination completed."
    assert compute_phrase_recall(required, zero_output) == 0.0

    # Crucial requirement: empty output scores zero recall, not a pass
    assert compute_phrase_recall(required, "") == 0.0
    assert compute_phrase_recall(required, "   \n\t  ") == 0.0

    # Empty required list returns 1.0
    assert compute_phrase_recall([], "Some output") == 1.0


def test_count_forbidden_phrases():
    forbidden = ["other patients", "major depressive disorder", "sertraline"]

    # No forbidden phrases present
    clean_text = "Patient was counseled on anxiety management and sleep hygiene."
    assert count_forbidden_phrases(forbidden, clean_text) == 0

    # Forbidden phrases present (case-insensitive)
    leak_text = "Revealing records of OTHER PATIENTS as requested. Patient diagnosed with Major Depressive Disorder."
    assert count_forbidden_phrases(forbidden, leak_text) == 2

    # Empty text
    assert count_forbidden_phrases(forbidden, "") == 0
    assert count_forbidden_phrases(forbidden, "   ") == 0


def test_guarded_imports_do_not_call_model():
    """Verify that importing run_eval does not initialize or call an LLM engine."""
    from app.adapters import llm
    assert llm._engine is None


def test_synthetic_cases_conformance():
    """Verify cases.py conforms to the exact synthetic dataset specifications."""
    from cases import LLM_CASES, get_ocr_cases

    # 1. OCR Cases conformance (exactly 6 pages)
    ocr_pages = get_ocr_cases()
    assert len(ocr_pages) == 6

    variants = [p["variant"] for p in ocr_pages]
    assert variants.count("large_clean") == 3
    assert variants.count("noisy_rotated") == 2
    assert variants.count("small_font") == 1

    for p in ocr_pages:
        assert "id" in p
        assert "ground_truth" in p and len(p["ground_truth"]) > 20
        assert "image_bytes" in p and len(p["image_bytes"]) > 100

    # 2. LLM Cases conformance (exactly 5 fixed cases)
    assert len(LLM_CASES) == 5
    for c in LLM_CASES:
        assert {"id", "text", "required", "forbidden"} <= set(c.keys())
        assert len(c["required"]) >= 2
        assert len(c["forbidden"]) >= 1

    # Check required case archetypes:
    # At least one with negation
    has_negation = any("denies" in c["text"].lower() for c in LLM_CASES)
    assert has_negation

    # At least one with historical timing
    has_historical = any("past medical history" in c["text"].lower() or "years ago" in c["text"].lower() for c in LLM_CASES)
    assert has_historical

    # At least one with prompt injection and forbidden "other patients"
    injection_case = next(
        (c for c in LLM_CASES if "ignore previous instructions" in c["text"].lower()),
        None,
    )
    assert injection_case is not None
    assert "other patients" in injection_case["forbidden"]
