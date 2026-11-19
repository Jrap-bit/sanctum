"""Unit tests for the report PDF renderer."""
from io import BytesIO

import pytest
from pypdf import PdfReader

from app.adapters.report_pdf import _clean, render


def manifest(**overrides):
    return {"patientName": "Synthetic Patient", "coverage": "1 Oct 2026 to 1 Nov 2026",
            "author": "Dr Clinician", "createdAt": "2026-11-02", "records": [], "excluded": [], **overrides}


def pages(data):
    assert data.startswith(b"%PDF")
    return [page.extract_text() for page in PdfReader(BytesIO(data)).pages]


def text_of(data):
    return "\n".join(pages(data))


@pytest.mark.unit
def test_header_and_empty_sections():
    text = text_of(render(manifest()))
    for expected in ["Sanctum clinical report", "Synthetic Patient", "Coverage: 1 Oct 2026 to 1 Nov 2026",
                     "Prepared by Dr Clinician on 2026-11-02", "Not included", "Nothing was excluded."]:
        assert expected in text
    for absent in ["Session records", "Approved summaries", "Reviewed indicators"]:
        assert absent not in text


@pytest.mark.unit
def test_all_record_kinds_and_exclusions():
    records = [
        {"kind": "session", "eventDate": "2026-10-05", "title": "Intake", "text": "Discussed sleep."},
        {"kind": "session", "eventDate": None, "title": None, "text": "Undated follow-up."},
        {"kind": "summary", "text": "Approved summary text."},
        {"kind": "indicator", "name": "Repeated concern", "reviewState": "acknowledged",
         "outcome": "matched", "explanation": "Raised in 3 sessions.", "ruleVersion": 2},
    ]
    excluded = [{"label": "Draft note", "reason": "Not finalised"}]
    text = text_of(render(manifest(records=records, excluded=excluded)))
    for expected in ["Session records", "2026-10-05 - Intake", "Discussed sleep.", "Undated - Session",
                     "Approved summaries", "Approved summary text.", "Reviewed indicators",
                     "Repeated concern (acknowledged)", "Outcome: matched", "Explanation: Raised in 3 sessions.",
                     "Rule version 2", "Draft note: Not finalised"]:
        assert expected in text
    assert "Nothing was excluded." not in text
    assert text.index("Session records") < text.index("Approved summaries") < text.index("Reviewed indicators")


@pytest.mark.unit
def test_included_key_is_accepted_when_records_absent():
    data = manifest(included=[{"kind": "summary", "text": "From included list."}])
    del data["records"]
    assert "From included list." in text_of(render(data))


@pytest.mark.unit
def test_unknown_record_kinds_are_ignored():
    text = text_of(render(manifest(records=[{"kind": "attachment", "text": "Hidden"}])))
    assert "Hidden" not in text


@pytest.mark.unit
def test_every_page_has_numbered_disclaimer_footer():
    long_note = {"kind": "session", "eventDate": "2026-10-05", "title": "Long", "text": "Line of notes. " * 800}
    page_texts = pages(render(manifest(records=[long_note])))
    assert len(page_texts) > 1
    for number, page_text in enumerate(page_texts, start=1):
        assert "Clinical judgment remains with the authorised practitioner." in page_text
        assert f"Page {number}" in page_text


@pytest.mark.unit
def test_non_latin1_text_does_not_break_rendering():
    data = render(manifest(patientName="Zoë “Quoted” 文字", records=[{"kind": "summary", "text": "Emoji 🙂 here"}]))
    text = text_of(data)
    assert "Zoë" in text
    assert "Emoji ? here" in text


@pytest.mark.parametrize("value,expected", [(None, ""), (12, "12"), ("café", "café"), ("文", "?"), ("a—b", "a?b")])
@pytest.mark.unit
def test_clean(value, expected):
    assert _clean(value) == expected
