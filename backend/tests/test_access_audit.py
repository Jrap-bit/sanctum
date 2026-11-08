from sqlalchemy import select

from app.db.models import AuditEvent
from test_patients import create, path, setup, sign_in  # noqa: F401


def denied_events(factory):
    with factory() as db:
        return db.scalars(select(AuditEvent).where(AuditEvent.action == "access.denied")).all()


def test_refused_patient_read_is_audited_without_disclosure(setup):
    client, factory, ids = setup
    patient = create(client)
    client.post("/api/v1/auth/logout")
    sign_in(client, "bob")

    response = client.get(path(patient))

    assert response.status_code == 404
    assert "Synthetic Alex" not in response.text
    events = denied_events(factory)
    assert len(events) == 1
    assert events[0].actor_id == ids["bob"]
    assert events[0].target_id == patient["id"]
    assert events[0].outcome == "denied"


def test_missing_capability_is_audited(setup):
    client, factory, ids = setup
    patient = create(client)
    client.post("/api/v1/auth/logout")
    sign_in(client, "admin")

    response = client.get(path(patient) + "/timeline")

    assert response.status_code in {403, 404}
    assert [event.actor_id for event in denied_events(factory)] == [ids["admin"]]


def test_permitted_read_records_no_denial(setup):
    client, factory, _ = setup
    patient = create(client)

    assert client.get(path(patient)).status_code == 200
    assert denied_events(factory) == []
