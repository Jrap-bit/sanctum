from hashlib import sha256
from uuid import uuid4

import pytest
from app.adapters.crypto import encrypt
from app.db.models import AISummary
from app.db.models import AuditEvent
from app.db.models import IndicatorRun
from app.db.models import Report
from app.services.indicators import digest
from app.services.indicators import snapshot as indicator_snapshot
from test_patients import create
from test_patients import path
from test_patients import setup
from test_patients import sign_in


def create_note(client, patient, event_date="2026-01-15"):
    res = client.post(path(patient) + "/sessions", json={"eventDate": event_date})
    assert res.status_code == 201, res.text
    return res.json()


def save_note(client, patient, note, text="Session clinical content", event_date="2026-01-15"):
    res = client.patch(
        path(patient) + f"/sessions/{note['id']}",
        json={
            "text": text,
            "eventDate": event_date,
            "concerns": [],
            "observations": [],
            "interventions": [],
            "medicationReported": [],
            "expectedVersion": note["version"],
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def finalize_note(client, patient, note):
    res = client.post(
        path(patient) + f"/sessions/{note['id']}/finalize",
        json={"expectedVersion": note["version"]},
    )
    assert res.status_code == 200, res.text
    return res.json()


def insert_summary(factory, patient_id, user_id, review_state, sources, text="Summary text"):
    sid = str(uuid4())
    payload = {
        "text": text,
        "reviewState": review_state,
        "sources": sources,
    }
    with factory() as db:
        summary = AISummary(
            id=sid,
            patient_id=patient_id,
            created_by=user_id,
            kind="single_session",
            version=1,
            payload=encrypt(payload, f"summary:{patient_id}:{sid}"),
        )
        db.add(summary)
        db.commit()
    return sid


def insert_indicator_run(factory, patient_id, user_id, results, reviews):
    rid = str(uuid4())
    with factory() as db:
        inp_digest = digest(indicator_snapshot(db, patient_id))
        run = IndicatorRun(
            id=rid,
            patient_id=patient_id,
            created_by=user_id,
            input_digest=inp_digest,
            version=1,
            payload=encrypt({"results": results}, f"indicator-run:{patient_id}:{rid}"),
            reviews=encrypt(reviews, f"indicator-reviews:{patient_id}:{rid}"),
        )
        db.add(run)
        db.commit()
    return rid


def test_eligible_sources(setup):
    client, _, _ = setup
    patient = create(client)
    n1 = finalize_note(client, patient, save_note(client, patient, create_note(client, patient, "2026-01-10"), "Note 1", "2026-01-10"))

    res = client.get(path(patient) + "/reports/eligible-sources")
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == n1["id"]
    assert items[0]["version"] == n1["version"]
    assert "text" not in items[0]


def test_preview_includes_notes_summaries_and_indicators(setup):
    client, factory, ids = setup
    patient = create(client)
    n1 = finalize_note(client, patient, save_note(client, patient, create_note(client, patient, "2026-01-10"), "First session", "2026-01-10"))
    n2 = finalize_note(client, patient, save_note(client, patient, create_note(client, patient, "2026-01-20"), "Second session", "2026-01-20"))

    n1_source = {"id": n1["id"], "version": n1["version"], "type": "session"}
    n2_source = {"id": n2["id"], "version": n2["version"], "type": "session"}

    accepted_sid = insert_summary(factory, patient["id"], ids["alice"], "accepted", [n1_source], "Accepted prose")
    pending_sid = insert_summary(factory, patient["id"], ids["alice"], "pending", [n1_source], "SecretPendingProse")
    rejected_sid = insert_summary(factory, patient["id"], ids["alice"], "rejected", [n1_source], "SecretRejectedProse")

    ind_results = [
        {"id": "ind-1", "name": "Overdue follow-up", "outcome": "matched", "explanation": "Follow-up overdue", "ruleVersion": 1},
        {"id": "ind-2", "name": "Medication review", "outcome": "not_matched", "explanation": "Medication current", "ruleVersion": 1},
    ]
    ind_reviews = {
        "ind-1": {"state": "acknowledged"},
    }
    insert_indicator_run(factory, patient["id"], ids["alice"], ind_results, ind_reviews)

    body = {
        "sourceVersions": [
            {"id": n1["id"], "version": n1["version"], "type": "session"},
            {"id": n2["id"], "version": n2["version"], "type": "session"},
        ]
    }
    res = client.post(path(patient) + "/reports/preview", json=body)
    assert res.status_code == 200, res.text
    data = res.json()

    assert data["patientName"] == "Synthetic Alex"
    assert data["coverage"] == "2026-01-10 to 2026-01-20"
    assert data["freshness"] == "current"

    included_ids = {x["id"] for x in data["included"]}
    assert n1["id"] in included_ids
    assert n2["id"] in included_ids
    assert accepted_sid in included_ids
    assert "ind-1" in included_ids

    # Unreviewed indicator, pending and rejected summaries must NOT be in included
    assert "ind-2" not in included_ids
    assert pending_sid not in included_ids
    assert rejected_sid not in included_ids

    # Pending and rejected text must appear nowhere in the response
    assert "SecretPendingProse" not in res.text
    assert "SecretRejectedProse" not in res.text

    # Excluded reasons check
    excluded_map = {x["label"]: x["reason"] for x in data["excluded"]}
    assert "Overdue follow-up" not in excluded_map
    assert excluded_map.get("Medication review") == "Not yet reviewed"
    summary_reasons = [x["reason"] for x in data["excluded"] if x["label"] == "AI summary"]
    assert "Awaiting review" in summary_reasons
    assert "Rejected" in summary_reasons


def test_stale_source_version_on_preview_returns_409(setup):
    client, _, _ = setup
    patient = create(client)
    n1 = finalize_note(client, patient, save_note(client, patient, create_note(client, patient, "2026-01-10"), "Session", "2026-01-10"))

    body = {
        "sourceVersions": [
            {"id": n1["id"], "version": 999, "type": "session"},
        ]
    }
    res = client.post(path(patient) + "/reports/preview", json=body)
    assert res.status_code == 409
    assert "A selected record changed. Refresh the list and try again." in res.text


def test_amending_note_after_preview_makes_export_return_409(setup):
    client, _, _ = setup
    patient = create(client)
    n1 = finalize_note(client, patient, save_note(client, patient, create_note(client, patient, "2026-01-10"), "Original note", "2026-01-10"))

    # Generate preview
    body = {
        "sourceVersions": [
            {"id": n1["id"], "version": n1["version"], "type": "session"},
        ]
    }
    preview_res = client.post(path(patient) + "/reports/preview", json=body)
    assert preview_res.status_code == 200, preview_res.text
    report_id = preview_res.json()["id"]

    # Amend note n1
    amend_draft = client.post(
        path(patient) + f"/sessions/{n1['id']}/amendments",
        json={"reason": "Correction required", "expectedVersion": n1["version"]},
    ).json()
    amend_saved = save_note(client, patient, amend_draft, "Amended note content", "2026-01-10")
    finalize_note(client, patient, amend_saved)

    # Export must fail with 409
    export_res = client.get(path(patient) + f"/reports/{report_id}/export")
    assert export_res.status_code == 409
    assert "A record in this preview changed. Create a new preview." in export_res.text


def test_export_pdf_success_digest_and_audit(setup):
    client, factory, _ = setup
    patient = create(client)
    n1 = finalize_note(client, patient, save_note(client, patient, create_note(client, patient, "2026-01-10"), "Valid clinical session", "2026-01-10"))

    body = {
        "sourceVersions": [
            {"id": n1["id"], "version": n1["version"], "type": "session"},
        ]
    }
    preview_res = client.post(path(patient) + "/reports/preview", json=body)
    assert preview_res.status_code == 200, preview_res.text
    report_id = preview_res.json()["id"]

    export_res = client.get(path(patient) + f"/reports/{report_id}/export")
    assert export_res.status_code == 200, export_res.text
    pdf_bytes = export_res.content

    assert pdf_bytes.startswith(b"%PDF-")
    assert export_res.headers["content-type"] == "application/pdf"
    assert export_res.headers["content-disposition"] == 'attachment; filename="sanctum-report.pdf"'
    assert export_res.headers["cache-control"] == "no-store"
    assert export_res.headers["x-content-type-options"] == "nosniff"

    with factory() as db:
        rep = db.get(Report, report_id)
        assert rep.state == "exported"
        assert rep.exported_at is not None
        assert rep.content_digest == sha256(pdf_bytes).hexdigest()

        audits = db.query(AuditEvent).filter(AuditEvent.action == "report.export", AuditEvent.target_id == report_id).all()
        assert len(audits) == 1


def test_unauthorised_user_gets_404_and_no_pdf(setup):
    client, _, _ = setup
    patient = create(client)
    n1 = finalize_note(client, patient, save_note(client, patient, create_note(client, patient, "2026-01-10"), "Session", "2026-01-10"))

    preview_res = client.post(
        path(patient) + "/reports/preview",
        json={"sourceVersions": [{"id": n1["id"], "version": n1["version"], "type": "session"}]},
    )
    assert preview_res.status_code == 200
    report_id = preview_res.json()["id"]

    # Bob has no access to Alice's patient
    sign_in(client, "bob")
    assert client.get(path(patient) + f"/reports/{report_id}/export").status_code == 404
    assert client.get(path(patient) + "/reports/eligible-sources").status_code == 404
    assert client.post(path(patient) + "/reports/preview", json={"sourceVersions": [{"id": n1["id"], "version": n1["version"], "type": "session"}]}).status_code == 404


def test_user_without_reports_write_gets_403(setup):
    client, _, _ = setup
    patient = create(client)
    n1 = finalize_note(client, patient, save_note(client, patient, create_note(client, patient, "2026-01-10"), "Session", "2026-01-10"))

    preview_res = client.post(
        path(patient) + "/reports/preview",
        json={"sourceVersions": [{"id": n1["id"], "version": n1["version"], "type": "session"}]},
    )
    assert preview_res.status_code == 200
    report_id = preview_res.json()["id"]

    # Admin has users:manage and audit:read, but lacks reports:write
    sign_in(client, "admin")
    assert client.get(path(patient) + "/reports/eligible-sources").status_code == 403
    assert client.post(path(patient) + "/reports/preview", json={"sourceVersions": [{"id": n1["id"], "version": n1["version"], "type": "session"}]}).status_code == 403
    assert client.get(path(patient) + f"/reports/{report_id}/export").status_code == 403
