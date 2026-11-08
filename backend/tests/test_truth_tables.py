from copy import deepcopy
from datetime import date
from datetime import timedelta
import pytest

from app.domain.rules.defaults import DEFAULTS
from app.domain.rules.dt01_repeated_concern import concern_results
from app.domain.rules.dt02_rating_increase import rating_results
from app.domain.rules.dt03_followup_outstanding import follow_up_result
from app.domain.rules.dt04_medication_change import medication_results
from app.domain.rules.dt05_required_documentation import documentation_results
from app.domain.rules.engine import compute

EVAL_DATE = date(2026, 11, 6)
EVAL_DATE_STR = "2026-11-06"


def _build_default_rules():
    return {
        key: {
            "id": key,
            **deepcopy(val),
            "version": 1,
            "enabled": True,
        }
        for key, val in DEFAULTS.items()
    }


def evaluate_8_6_2_row(row_id: str) -> str:
    if row_id == "dt01-3of3":
        sessions = [
            {"id": "s1", "version": 1, "dateStatus": "known", "eventDate": "2026-11-01", "href": "/s1"},
            {"id": "s2", "version": 1, "dateStatus": "known", "eventDate": "2026-11-02", "href": "/s2"},
            {"id": "s3", "version": 1, "dateStatus": "known", "eventDate": "2026-11-03", "href": "/s3"},
        ]
        concerns = [
            {
                "sourceId": s["id"],
                "sourceVersion": s["version"],
                "concernCode": "anxiety",
                "state": "confirmed",
                "freshness": "current",
                "assertion": "present",
                "temporality": "current",
                "subject": "patient",
                "quotation": "feels anxious",
            }
            for s in sessions
        ]
        res = concern_results(concerns, sessions, EVAL_DATE, window=3, threshold=3)
        return res[0]["outcome"]

    if row_id == "dt01-denied":
        sessions = [
            {"id": "s1", "version": 1, "dateStatus": "known", "eventDate": "2026-11-01", "href": "/s1"},
            {"id": "s2", "version": 1, "dateStatus": "known", "eventDate": "2026-11-02", "href": "/s2"},
            {"id": "s3", "version": 1, "dateStatus": "known", "eventDate": "2026-11-03", "href": "/s3"},
        ]
        concerns = [
            {
                "sourceId": "s1",
                "sourceVersion": 1,
                "concernCode": "anxiety",
                "state": "confirmed",
                "freshness": "current",
                "assertion": "present",
                "temporality": "current",
                "subject": "patient",
                "quotation": "anxious",
            },
            {
                "sourceId": "s2",
                "sourceVersion": 1,
                "concernCode": "anxiety",
                "state": "confirmed",
                "freshness": "current",
                "assertion": "present",
                "temporality": "current",
                "subject": "patient",
                "quotation": "anxious",
            },
            {
                "sourceId": "s3",
                "sourceVersion": 1,
                "concernCode": "anxiety",
                "state": "confirmed",
                "freshness": "current",
                "assertion": "denied",
                "temporality": "current",
                "subject": "patient",
                "quotation": "denies anxiety",
            },
        ]
        res = concern_results(concerns, sessions, EVAL_DATE, window=3, threshold=3)
        return res[0]["outcome"]

    if row_id == "dt01-too-few":
        sessions = [
            {"id": "s1", "version": 1, "dateStatus": "known", "eventDate": "2026-11-01", "href": "/s1"},
            {"id": "s2", "version": 1, "dateStatus": "known", "eventDate": "2026-11-02", "href": "/s2"},
        ]
        concerns = [
            {
                "sourceId": s["id"],
                "sourceVersion": s["version"],
                "concernCode": "anxiety",
                "state": "confirmed",
                "freshness": "current",
                "assertion": "present",
                "temporality": "current",
                "subject": "patient",
                "quotation": "anxious",
            }
            for s in sessions
        ]
        res = concern_results(concerns, sessions, EVAL_DATE, window=3, threshold=3)
        return res[0]["outcome"]

    if row_id == "dt02-equal-threshold":
        ratings = [
            {
                "id": "r1",
                "scaleName": "PHQ-9",
                "value": 4.0,
                "state": "confirmed",
                "freshness": "current",
                "dateStatus": "known",
                "eventDate": "2026-10-20",
                "higherMeans": "more_difficulty",
                "href": "/r1",
            },
            {
                "id": "r2",
                "scaleName": "PHQ-9",
                "value": 6.0,
                "state": "confirmed",
                "freshness": "current",
                "dateStatus": "known",
                "eventDate": "2026-11-01",
                "higherMeans": "more_difficulty",
                "href": "/r2",
            },
        ]
        res = rating_results(ratings, EVAL_DATE, threshold=2)
        return res[0]["outcome"]

    if row_id == "dt02-below":
        ratings = [
            {
                "id": "r1",
                "scaleName": "PHQ-9",
                "value": 4.0,
                "state": "confirmed",
                "freshness": "current",
                "dateStatus": "known",
                "eventDate": "2026-10-20",
                "higherMeans": "more_difficulty",
                "href": "/r1",
            },
            {
                "id": "r2",
                "scaleName": "PHQ-9",
                "value": 5.0,
                "state": "confirmed",
                "freshness": "current",
                "dateStatus": "known",
                "eventDate": "2026-11-01",
                "higherMeans": "more_difficulty",
                "href": "/r2",
            },
        ]
        res = rating_results(ratings, EVAL_DATE, threshold=2)
        return res[0]["outcome"]

    if row_id == "dt02-missing":
        ratings = [
            {
                "id": "r1",
                "scaleName": "PHQ-9",
                "value": 4.0,
                "state": "confirmed",
                "freshness": "current",
                "dateStatus": "known",
                "eventDate": "2026-10-20",
                "higherMeans": "more_difficulty",
                "href": "/r1",
            }
        ]
        res = rating_results(ratings, EVAL_DATE, threshold=2)
        return res[0]["outcome"]

    if row_id == "dt02-different-scale":
        ratings = [
            {
                "id": "r1",
                "scaleName": "PHQ-9",
                "value": 4.0,
                "state": "confirmed",
                "freshness": "current",
                "dateStatus": "known",
                "eventDate": "2026-10-20",
                "higherMeans": "more_difficulty",
                "href": "/r1",
            },
            {
                "id": "r2",
                "scaleName": "GAD-7",
                "value": 6.0,
                "state": "confirmed",
                "freshness": "current",
                "dateStatus": "known",
                "eventDate": "2026-11-01",
                "higherMeans": "more_difficulty",
                "href": "/r2",
            },
        ]
        res = rating_results(ratings, EVAL_DATE, threshold=2)
        # Both scales have only 1 rating, hence both return not_evaluable
        assert len(res) == 2
        assert all(r["outcome"] == "not_evaluable" for r in res)
        return res[0]["outcome"]

    if row_id == "dt03-yesterday":
        task = {
            "id": "t1",
            "title": "Care coordination",
            "state": "open",
            "dueDate": "2026-11-05",
        }
        outcome, _ = follow_up_result(task, EVAL_DATE)
        return outcome

    if row_id == "dt03-today":
        task = {
            "id": "t1",
            "title": "Care coordination",
            "state": "open",
            "dueDate": "2026-11-06",
        }
        outcome, _ = follow_up_result(task, EVAL_DATE)
        return outcome

    if row_id == "dt04-boundary":
        # 30 days before 2026-11-06 is 2026-10-07
        event_date = (EVAL_DATE - timedelta(days=30)).isoformat()
        records = [
            {
                "id": "m1",
                "medicationName": "Sertraline",
                "state": "confirmed",
                "freshness": "current",
                "dateStatus": "known",
                "eventDate": event_date,
                "changeStatus": "changed",
                "href": "/m1",
                "quotation": "Increased sertraline dose",
            }
        ]
        res = medication_results(records, EVAL_DATE, lookback=30)
        return res[0]["outcome"]

    if row_id == "dt04-unknown-date":
        records = [
            {
                "id": "m1",
                "medicationName": "Sertraline",
                "state": "confirmed",
                "freshness": "current",
                "dateStatus": "unknown",
                "eventDate": None,
                "changeStatus": "uncertain",
                "href": "/m1",
                "quotation": "Possible change",
            }
        ]
        res = medication_results(records, EVAL_DATE, lookback=30)
        return res[0]["outcome"]

    if row_id == "dt05-complete":
        snapshot = {
            "template": {"id": "session-default", "version": 1, "name": "Session note"},
            "sessions": [
                {
                    "id": "sess-1",
                    "version": 1,
                    "sourceType": "clinical_note",
                    "dateStatus": "known",
                    "eventDate": "2026-11-01",
                    "hasStructuredContent": True,
                    "href": "/notes/sess-1",
                }
            ],
        }
        res = documentation_results(snapshot)
        return res[0]["outcome"]

    if row_id == "dt05-empty":
        snapshot = {
            "template": {"id": "session-default", "version": 1, "name": "Session note"},
            "sessions": [
                {
                    "id": "sess-1",
                    "version": 1,
                    "sourceType": "clinical_note",
                    "dateStatus": "known",
                    "eventDate": "2026-11-01",
                    "hasStructuredContent": False,
                    "href": "/notes/sess-1",
                }
            ],
        }
        res = documentation_results(snapshot)
        return res[0]["outcome"]

    raise ValueError(f"Unknown row id: {row_id}")


REQUIRED_ROWS = [
    ("dt01-3of3", "matched"),
    ("dt01-denied", "not_matched"),
    ("dt01-too-few", "not_evaluable"),
    ("dt02-equal-threshold", "matched"),
    ("dt02-below", "not_matched"),
    ("dt02-missing", "not_evaluable"),
    ("dt02-different-scale", "not_evaluable"),
    ("dt03-yesterday", "matched"),
    ("dt03-today", "not_matched"),
    ("dt04-boundary", "matched"),
    ("dt04-unknown-date", "not_evaluable"),
    ("dt05-complete", "not_matched"),
    ("dt05-empty", "matched"),
]


@pytest.mark.parametrize("row_id, expected", REQUIRED_ROWS, ids=[r[0] for r in REQUIRED_ROWS])
def test_required_rows_8_6_2(row_id: str, expected: str):
    actual = evaluate_8_6_2_row(row_id)
    assert actual == expected


# Additional boundary and negation rows


def test_dt01_possible_assertion_not_evaluable():
    """dt01: `possible` assertion is not counted as present and yields not_evaluable."""
    sessions = [
        {"id": "s1", "version": 1, "dateStatus": "known", "eventDate": "2026-11-01", "href": "/s1"},
        {"id": "s2", "version": 1, "dateStatus": "known", "eventDate": "2026-11-02", "href": "/s2"},
        {"id": "s3", "version": 1, "dateStatus": "known", "eventDate": "2026-11-03", "href": "/s3"},
    ]
    concerns = [
        {
            "sourceId": "s1",
            "sourceVersion": 1,
            "concernCode": "anxiety",
            "state": "confirmed",
            "freshness": "current",
            "assertion": "present",
            "temporality": "current",
            "subject": "patient",
            "quotation": "anxious",
        },
        {
            "sourceId": "s2",
            "sourceVersion": 1,
            "concernCode": "anxiety",
            "state": "confirmed",
            "freshness": "current",
            "assertion": "present",
            "temporality": "current",
            "subject": "patient",
            "quotation": "anxious",
        },
        {
            "sourceId": "s3",
            "sourceVersion": 1,
            "concernCode": "anxiety",
            "state": "confirmed",
            "freshness": "current",
            "assertion": "possible",
            "temporality": "current",
            "subject": "patient",
            "quotation": "possible anxiety",
        },
    ]
    res = concern_results(concerns, sessions, EVAL_DATE, window=3, threshold=3)
    assert res[0]["outcome"] == "not_evaluable"


def test_dt01_undated_sessions_excluded():
    """dt01: undated sessions excluded from the window."""
    sessions = [
        {"id": "s1", "version": 1, "dateStatus": "known", "eventDate": "2026-11-01", "href": "/s1"},
        {"id": "s2", "version": 1, "dateStatus": "known", "eventDate": "2026-11-02", "href": "/s2"},
        {"id": "s3", "version": 1, "dateStatus": "unknown", "eventDate": None, "href": "/s3"},
    ]
    concerns = [
        {
            "sourceId": s["id"],
            "sourceVersion": s["version"],
            "concernCode": "anxiety",
            "state": "confirmed",
            "freshness": "current",
            "assertion": "present",
            "temporality": "current",
            "subject": "patient",
            "quotation": "anxious",
        }
        for s in sessions
    ]
    res = concern_results(concerns, sessions, EVAL_DATE, window=3, threshold=3)
    assert res[0]["outcome"] == "not_evaluable"


def test_dt01_k2_w3_with_2_present_matched():
    """dt01: K=2, W=3 with 2 present yields matched."""
    sessions = [
        {"id": "s1", "version": 1, "dateStatus": "known", "eventDate": "2026-11-01", "href": "/s1"},
        {"id": "s2", "version": 1, "dateStatus": "known", "eventDate": "2026-11-02", "href": "/s2"},
        {"id": "s3", "version": 1, "dateStatus": "known", "eventDate": "2026-11-03", "href": "/s3"},
    ]
    concerns = [
        {
            "sourceId": "s1",
            "sourceVersion": 1,
            "concernCode": "anxiety",
            "state": "confirmed",
            "freshness": "current",
            "assertion": "present",
            "temporality": "current",
            "subject": "patient",
            "quotation": "anxious",
        },
        {
            "sourceId": "s2",
            "sourceVersion": 1,
            "concernCode": "anxiety",
            "state": "confirmed",
            "freshness": "current",
            "assertion": "present",
            "temporality": "current",
            "subject": "patient",
            "quotation": "anxious",
        },
        {
            "sourceId": "s3",
            "sourceVersion": 1,
            "concernCode": "anxiety",
            "state": "confirmed",
            "freshness": "current",
            "assertion": "denied",
            "temporality": "current",
            "subject": "patient",
            "quotation": "denies anxiety",
        },
    ]
    res = concern_results(concerns, sessions, EVAL_DATE, window=3, threshold=2)
    assert res[0]["outcome"] == "matched"


def test_dt02_d3_not_matched():
    """dt02: previous 4, current 6, D=3 yields not_matched."""
    ratings = [
        {
            "id": "r1",
            "scaleName": "PHQ-9",
            "value": 4.0,
            "state": "confirmed",
            "freshness": "current",
            "dateStatus": "known",
            "eventDate": "2026-10-20",
            "higherMeans": "more_difficulty",
            "href": "/r1",
        },
        {
            "id": "r2",
            "scaleName": "PHQ-9",
            "value": 6.0,
            "state": "confirmed",
            "freshness": "current",
            "dateStatus": "known",
            "eventDate": "2026-11-01",
            "higherMeans": "more_difficulty",
            "href": "/r2",
        },
    ]
    res = rating_results(ratings, EVAL_DATE, threshold=3)
    assert res[0]["outcome"] == "not_matched"


def test_dt02_31_days_old_outside_window():
    """dt02: a rating 31 days old is outside the window."""
    older_date = (EVAL_DATE - timedelta(days=31)).isoformat()
    ratings = [
        {
            "id": "r1",
            "scaleName": "PHQ-9",
            "value": 4.0,
            "state": "confirmed",
            "freshness": "current",
            "dateStatus": "known",
            "eventDate": older_date,
            "higherMeans": "more_difficulty",
            "href": "/r1",
        },
        {
            "id": "r2",
            "scaleName": "PHQ-9",
            "value": 6.0,
            "state": "confirmed",
            "freshness": "current",
            "dateStatus": "known",
            "eventDate": "2026-11-01",
            "higherMeans": "more_difficulty",
            "href": "/r2",
        },
    ]
    res = rating_results(ratings, EVAL_DATE, threshold=2)
    assert res[0]["outcome"] == "not_evaluable"


def test_dt02_equal_rating_never_matches():
    """dt02: an equal rating never matches."""
    ratings = [
        {
            "id": "r1",
            "scaleName": "PHQ-9",
            "value": 4.0,
            "state": "confirmed",
            "freshness": "current",
            "dateStatus": "known",
            "eventDate": "2026-10-20",
            "higherMeans": "more_difficulty",
            "href": "/r1",
        },
        {
            "id": "r2",
            "scaleName": "PHQ-9",
            "value": 4.0,
            "state": "confirmed",
            "freshness": "current",
            "dateStatus": "known",
            "eventDate": "2026-11-01",
            "higherMeans": "more_difficulty",
            "href": "/r2",
        },
    ]
    res = rating_results(ratings, EVAL_DATE, threshold=2)
    assert res[0]["outcome"] == "not_matched"


def test_dt03_no_due_date_not_evaluable():
    """dt03: open with no due date is not_evaluable."""
    task = {
        "id": "t1",
        "title": "Care coordination",
        "state": "open",
        "dueDate": None,
    }
    outcome, _ = follow_up_result(task, EVAL_DATE)
    assert outcome == "not_evaluable"


def test_dt03_completed_and_cancelled_overdue_not_matched():
    """dt03: completed and cancelled overdue tasks are not_matched."""
    completed_task = {
        "id": "t1",
        "title": "Care coordination",
        "state": "completed",
        "dueDate": "2026-11-05",
    }
    cancelled_task = {
        "id": "t2",
        "title": "Care coordination",
        "state": "cancelled",
        "dueDate": "2026-11-05",
    }
    completed_outcome, _ = follow_up_result(completed_task, EVAL_DATE)
    cancelled_outcome, _ = follow_up_result(cancelled_task, EVAL_DATE)
    assert completed_outcome == "not_matched"
    assert cancelled_outcome == "not_matched"


def test_dt04_31_days_old_not_matched():
    """dt04: 31 days old with L=30 is not_matched."""
    event_date = (EVAL_DATE - timedelta(days=31)).isoformat()
    records = [
        {
            "id": "m1",
            "medicationName": "Sertraline",
            "state": "confirmed",
            "freshness": "current",
            "dateStatus": "known",
            "eventDate": event_date,
            "changeStatus": "changed",
            "href": "/m1",
            "quotation": "Dose adjusted",
        }
    ]
    res = medication_results(records, EVAL_DATE, lookback=30)
    assert res[0]["outcome"] == "not_matched"


def test_dt04_l1_boundary_matched():
    """dt04: L=1 boundary is matched at exactly 1 day."""
    event_date = (EVAL_DATE - timedelta(days=1)).isoformat()
    records = [
        {
            "id": "m1",
            "medicationName": "Sertraline",
            "state": "confirmed",
            "freshness": "current",
            "dateStatus": "known",
            "eventDate": event_date,
            "changeStatus": "changed",
            "href": "/m1",
            "quotation": "Dose adjusted",
        }
    ]
    res = medication_results(records, EVAL_DATE, lookback=1)
    assert res[0]["outcome"] == "matched"


def test_dt04_no_change_not_matched():
    """dt04: `no_change` is not_matched."""
    event_date = (EVAL_DATE - timedelta(days=5)).isoformat()
    records = [
        {
            "id": "m1",
            "medicationName": "Sertraline",
            "state": "confirmed",
            "freshness": "current",
            "dateStatus": "known",
            "eventDate": event_date,
            "changeStatus": "no_change",
            "href": "/m1",
            "quotation": "No change to medication",
        }
    ]
    res = medication_results(records, EVAL_DATE, lookback=30)
    assert res[0]["outcome"] == "not_matched"


def test_dt04_no_entries_not_evaluable():
    """dt04: no entries at all is not_evaluable."""
    res = medication_results([], EVAL_DATE, lookback=30)
    assert res[0]["outcome"] == "not_evaluable"


def test_dt05_unknown_date_content_present_not_matched():
    """dt05: unknown date status with no date and content present is not_matched."""
    snapshot = {
        "template": {"id": "session-default", "version": 1, "name": "Session note"},
        "sessions": [
            {
                "id": "sess-1",
                "version": 1,
                "sourceType": "clinical_note",
                "dateStatus": "unknown",
                "eventDate": None,
                "hasStructuredContent": True,
                "href": "/notes/sess-1",
            }
        ],
    }
    res = documentation_results(snapshot)
    assert res[0]["outcome"] == "not_matched"


def test_dt05_missing_date_status_matched_and_names_field():
    """dt05: a missing date status is matched and names the missing field."""
    snapshot = {
        "template": {"id": "session-default", "version": 1, "name": "Session note"},
        "sessions": [
            {
                "id": "sess-1",
                "version": 1,
                "sourceType": "clinical_note",
                "dateStatus": None,
                "eventDate": None,
                "hasStructuredContent": True,
                "href": "/notes/sess-1",
            }
        ],
    }
    res = documentation_results(snapshot)
    assert res[0]["outcome"] == "matched"
    assert "Date status" in res[0]["missingFields"]


def test_engine_disabled_rule_reports_not_evaluable_with_explanation():
    """Engine: `compute` with a rule disabled reports it `not_evaluable` with the disabled explanation."""
    rules = _build_default_rules()
    rules["repeated-concern"]["enabled"] = False
    inputs = {
        "evaluationDate": EVAL_DATE_STR,
        "tasks": [],
        "ratings": [],
        "concerns": [],
        "sessions": [],
        "medications": [],
        "documentation": {
            "template": {"id": "session-default", "version": 1, "name": "Session note"},
            "sessions": [],
        },
        "rules": rules,
    }
    results = compute(inputs, "patient-123")
    disabled_item = next(r for r in results if r["ruleId"] == "repeated-concern")
    assert disabled_item["outcome"] == "not_evaluable"
    assert disabled_item["explanation"] == "This rule was disabled at evaluation. No result was calculated."


def test_engine_metadata_carried_on_every_result():
    """Engine: Every result carries `ruleVersion`, `explanation`, and `conditions`."""
    rules = _build_default_rules()
    inputs = {
        "evaluationDate": EVAL_DATE_STR,
        "tasks": [{"id": "t1", "title": "Checkup", "state": "open", "dueDate": "2026-11-01"}],
        "ratings": [],
        "concerns": [],
        "sessions": [],
        "medications": [],
        "documentation": {
            "template": {"id": "session-default", "version": 1, "name": "Session note"},
            "sessions": [],
        },
        "rules": rules,
    }
    results = compute(inputs, "patient-123")
    assert len(results) > 0
    for item in results:
        assert "ruleVersion" in item
        assert "explanation" in item
        assert "conditions" in item


def test_engine_missing_inputs_never_reported_as_not_matched():
    """Engine: Missing inputs are never reported as `not_matched`."""
    rules = _build_default_rules()
    inputs = {
        "evaluationDate": EVAL_DATE_STR,
        "tasks": [],
        "ratings": [],
        "concerns": [],
        "sessions": [],
        "medications": [],
        "documentation": {
            "template": {"id": "session-default", "version": 1, "name": "Session note"},
            "sessions": [],
        },
        "rules": rules,
    }
    results = compute(inputs, "patient-123")
    for item in results:
        assert item["outcome"] != "not_matched", f"Rule {item['ruleId']} reported not_matched on missing inputs"
        assert item["outcome"] == "not_evaluable"
