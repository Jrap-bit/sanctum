from datetime import datetime
from datetime import timedelta
from datetime import timezone
from uuid import uuid4

import pytest
from app.db.models import AuditEvent
from test_patients import create
from test_patients import path
from test_patients import setup
from test_patients import sign_in


def test_requires_audit_read(setup):
    client, _, _ = setup
    # Alice is clinician, lacks audit:read
    res = client.get("/api/v1/audit")
    assert res.status_code == 403, res.text

    # Admin has audit:read
    sign_in(client, "admin")
    res = client.get("/api/v1/audit")
    assert res.status_code == 200, res.text


def test_limit_above_100_returns_422(setup):
    client, _, _ = setup
    sign_in(client, "admin")
    res = client.get("/api/v1/audit?limit=101")
    assert res.status_code == 422, res.text


def test_methods_post_and_delete_return_405(setup):
    client, _, _ = setup
    sign_in(client, "admin")
    assert client.post("/api/v1/audit", json={}).status_code == 405
    assert client.delete("/api/v1/audit").status_code == 405


def test_filters_work(setup):
    client, factory, ids = setup
    sign_in(client, "alice")
    patient = create(client)

    sign_in(client, "admin")
    # Action substring filter
    res = client.get("/api/v1/audit?action=patient.")
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert len(items) > 0
    assert all("patient." in item["action"] for item in items)

    # Actor ID filter
    res = client.get(f"/api/v1/audit?actorId={ids['alice']}")
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert len(items) > 0
    assert all(item["actorId"] == ids["alice"] for item in items)

    # Date filters
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    res = client.get(f"/api/v1/audit?from={yesterday.isoformat()}&to={tomorrow.isoformat()}")
    assert res.status_code == 200, res.text
    assert len(res.json()["items"]) > 0

    past_date = today - timedelta(days=10)
    res = client.get(f"/api/v1/audit?from={past_date.isoformat()}&to={past_date.isoformat()}")
    assert res.status_code == 200, res.text
    assert len(res.json()["items"]) == 0

    # Invalid dates return 422
    assert client.get("/api/v1/audit?from=invalid-date").status_code == 422
    assert client.get("/api/v1/audit?to=invalid-date").status_code == 422


def test_response_contains_no_note_text_after_note_saved(setup):
    client, _, _ = setup
    sign_in(client, "alice")
    patient = create(client)

    secret_clinical_text = "PrivatePsychiatricEvaluation-987654"
    res = client.post(path(patient) + "/sessions", json={"eventDate": "2026-02-01"})
    note = res.json()
    client.patch(
        path(patient) + f"/sessions/{note['id']}",
        json={
            "text": secret_clinical_text,
            "eventDate": "2026-02-01",
            "concerns": [],
            "observations": [],
            "interventions": [],
            "medicationReported": [],
            "expectedVersion": note["version"],
        },
    )

    sign_in(client, "admin")
    audit_res = client.get("/api/v1/audit")
    assert audit_res.status_code == 200
    assert secret_clinical_text not in audit_res.text


def test_pagination_with_before_works(setup):
    client, factory, ids = setup
    base_time = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
    with factory() as db:
        for i in range(5):
            db.add(
                AuditEvent(
                    id=f"page-test-{i}",
                    actor_id=ids["admin"],
                    action=f"pagination.action.{i}",
                    outcome="success",
                    request_id=str(uuid4()),
                    created_at=base_time + timedelta(minutes=i),
                )
            )
        db.commit()

    sign_in(client, "admin")
    # Request page 1 with limit=2
    res1 = client.get("/api/v1/audit?action=pagination.action&limit=2")
    assert res1.status_code == 200, res1.text
    data1 = res1.json()
    assert len(data1["items"]) == 2
    assert data1["nextBefore"] is not None
    page1_ids = [item["id"] for item in data1["items"]]

    # Request page 2 with before=nextBefore
    res2 = client.get(f"/api/v1/audit?action=pagination.action&limit=2&before={data1['nextBefore']}")
    assert res2.status_code == 200, res2.text
    data2 = res2.json()
    assert len(data2["items"]) == 2
    page2_ids = [item["id"] for item in data2["items"]]

    # The pages must have no overlapping IDs
    assert set(page1_ids).isdisjoint(set(page2_ids))
