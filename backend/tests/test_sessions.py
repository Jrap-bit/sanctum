from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from app.main import app
from app.models import AuditEvent, ClinicalNote, PatientAccess, User
from app.security import COOKIE_NAME
from test_patients import setup, create, path, sign_in  # Shared isolated database/key fixture.


def new_note(client, patient, event_date="2026-01-15"):
    response = client.post(path(patient) + "/sessions", json={"eventDate": event_date})
    assert response.status_code == 201, response.text
    return response.json()


def url(patient, note):
    return path(patient) + "/sessions/" + note["id"]


def content(note, **changes):
    keys = ("text", "eventDate", "concerns", "observations", "interventions", "medicationReported")
    return {**{k: note[k] for k in keys}, "expectedVersion": note["version"], **changes}


def saved(client, patient, note, **changes):
    response = client.patch(url(patient, note), json=content(note, **changes))
    assert response.status_code == 200, response.text
    return response.json()


def finalized(client, patient, note):
    response = client.post(url(patient, note) + "/finalize", json={"expectedVersion": note["version"]})
    assert response.status_code == 200, response.text
    return response.json()


def test_create_save_finalize_read_and_immutable_content(setup):
    client, factory, _ = setup
    patient = create(client)
    note = new_note(client, patient)
    assert note["state"] == "draft" and note["version"] == 1
    assert note["allowedActions"] == ["edit", "finalize"]
    note = saved(client, patient, note, text="Synthetic concern discussed.")
    assert note["version"] == 2
    note = finalized(client, patient, note)
    assert note["state"] == "finalized" and note["version"] == 3
    assert note["allowedActions"] == ["amend"]
    assert client.patch(url(patient, note), json=content(note, text="Overwrite")).status_code == 409
    with TestClient(app) as fresh:
        fresh.cookies.set(COOKIE_NAME, client.cookies.get(COOKIE_NAME))
        assert fresh.get(url(patient, note)).json()["text"] == "Synthetic concern discussed."
    with factory() as db:
        row = db.get(ClinicalNote, note["id"])
        assert row.finalized_at is not None
        assert b"Synthetic concern" not in row.payload
        actions = {e.action for e in db.scalars(select(AuditEvent).where(AuditEvent.target_id == row.id))}
        assert actions >= {"session.create", "session.save", "session.finalize", "session.read"}
    events = client.get(path(patient) + "/timeline").json()["items"]
    item = next(e for e in events if e["id"] == note["id"])
    assert item["status"] == "finalized"
    assert item["href"].endswith('/sessions/' + note["id"])


def test_empty_finalization_rejected_but_structured_note_accepted(setup):
    client, _, _ = setup
    patient = create(client)
    note = new_note(client, patient)
    assert client.post(url(patient, note) + "/finalize", json={"expectedVersion": 1}).status_code == 422
    note = saved(client, patient, note, text="  ", concerns=[{"text": "  ", "assertion": "unknown", "temporality": "unknown"}])
    assert client.post(url(patient, note) + "/finalize", json={"expectedVersion": note["version"]}).status_code == 422
    note = saved(client, patient, note, concerns=[{"text": "Sleep concern denied", "assertion": "denied", "temporality": "current"}])
    final = finalized(client, patient, note)
    assert final["concerns"][0]["assertion"] == "denied"


def test_stale_save_and_finalize_cannot_overwrite_newer_text(setup):
    client, _, _ = setup
    patient = create(client)
    old = new_note(client, patient)
    current = saved(client, patient, old, text="First writer")
    response = client.patch(url(patient, old), json=content(old, text="Stale second writer"))
    assert response.status_code == 409
    assert response.json()["code"] == "VERSION_CONFLICT"
    assert client.post(url(patient, old) + "/finalize", json={"expectedVersion": 1}).status_code == 409
    assert client.get(url(patient, old)).json()["text"] == current["text"]


def test_unknown_date_preserved_in_timeline(setup):
    client, _, _ = setup
    patient = create(client)
    note = saved(client, patient, new_note(client, patient, None), text="Undated historical account")
    finalized(client, patient, note)
    event = next(e for e in client.get(path(patient) + "/timeline").json()["items"] if e["id"] == note["id"])
    assert event["eventDate"] is None
    assert event["createdAt"] is not None


def test_cross_patient_and_unassigned_access_denied(setup):
    client, _, _ = setup
    patient, other = create(client), create(client, displayName="Other synthetic patient")
    note = new_note(client, patient)
    assert client.get(url(other, note)).status_code == 404
    assert client.patch(url(other, note), json=content(note, text="wrong parent")).status_code == 404
    sign_in(client, "bob")
    assert client.get(url(patient, note)).status_code == 404
    assert client.post(path(patient) + "/sessions", json={"eventDate": None}).status_code == 404
    sign_in(client, "admin")
    assert client.get(url(patient, note)).status_code == 403


def test_shared_scope_does_not_allow_editing_another_authors_draft(setup):
    client, factory, ids = setup
    patient = create(client)
    note = saved(client, patient, new_note(client, patient), text="Alice's draft")
    with factory() as db:
        db.add(PatientAccess(patient_id=patient["id"], user_id=ids["bob"]))
        db.commit()
    sign_in(client, "bob")
    assert client.get(url(patient, note)).json()["allowedActions"] == []
    assert client.patch(url(patient, note), json=content(note, text="Bob's edit")).status_code == 403
    assert client.post(url(patient, note) + "/finalize", json={"expectedVersion": note["version"]}).status_code == 403
    sign_in(client, "alice")
    final = finalized(client, patient, note)
    sign_in(client, "bob")
    response = client.post(url(patient, final) + "/amendments", json={"expectedVersion": final["version"], "reason": "Attributed correction"})
    assert response.status_code == 201
    assert response.json()["author"] == "Bob"
    assert response.json()["versions"][0]["author"] == "Alice"


def test_amendment_chain_preserves_original_and_reason(setup):
    client, factory, _ = setup
    patient = create(client)
    original = finalized(client, patient, saved(client, patient, new_note(client, patient), text="Original content"))
    with factory() as db:
        original_ciphertext = db.get(ClinicalNote, original["id"]).payload
    data = {"reason": "Correct a transcription", "expectedVersion": original["version"]}
    response = client.post(url(patient, original) + "/amendments", json=data)
    assert response.status_code == 201
    draft = response.json()
    assert draft["id"] != original["id"] and draft["state"] == "draft"
    assert draft["version"] > original["version"]
    assert draft["versions"][0]["text"] == "Original content"
    assert client.post(url(patient, original) + "/amendments", json=data).status_code == 409
    assert client.get(url(patient, original)).json()["allowedActions"] == []
    draft = saved(client, patient, draft, text="Corrected content", eventDate=None)
    final = finalized(client, patient, draft)
    assert final["amendmentReason"] == data["reason"]
    assert final["versions"][0]["eventDate"] == original["eventDate"]
    with factory() as db:
        assert db.get(ClinicalNote, original["id"]).payload == original_ciphertext
    next_draft = client.post(url(patient, final) + "/amendments", json={"reason": "Second correction", "expectedVersion": final["version"]}).json()
    assert [v["text"] for v in next_draft["versions"]] == ["Corrected content", "Original content"]


@pytest.mark.parametrize("reason", ["", "   "])
def test_amendment_reason_required(setup, reason):
    client, _, _ = setup
    patient = create(client)
    note = finalized(client, patient, saved(client, patient, new_note(client, patient), text="Original"))
    assert client.post(url(patient, note) + "/amendments", json={"expectedVersion": note["version"], "reason": reason}).status_code == 422


def test_archived_patient_notes_are_readable_but_not_writable(setup):
    client, _, _ = setup
    patient = create(client)
    note = new_note(client, patient)
    client.post(path(patient) + "/archive", json={"expectedVersion": 1})
    assert client.get(url(patient, note)).json()["allowedActions"] == []
    assert client.patch(url(patient, note), json=content(note, text="blocked")).status_code == 409
    assert client.post(path(patient) + "/sessions", json={"eventDate": None}).status_code == 409


def test_validation_protects_author_state_and_structured_semantics(setup):
    client, _, _ = setup
    patient = create(client)
    note = new_note(client, patient)
    for extra in [{"author": "Someone else"}, {"state": "finalized"}, {"amendmentReason": "rewrite"},
                  {"concerns": [{"text": "Concern", "assertion": "diagnosed", "temporality": "current"}]},
                  {"eventDate": (date.today() + timedelta(days=5)).isoformat()}]:
        assert client.patch(url(patient, note), json=content(note, **extra)).status_code == 422
    assert client.patch(url(patient, note), json={"expectedVersion": 1, "text": "Incomplete snapshot"}).status_code == 422


def test_revocation_and_deactivation_apply_to_existing_notes(setup):
    client, factory, ids = setup
    patient = create(client)
    note = new_note(client, patient)
    with factory() as db:
        db.execute(delete(PatientAccess).where(PatientAccess.patient_id == patient["id"]))
        db.commit()
    assert client.get(url(patient, note)).status_code == 404
    with factory() as db:
        db.get(User, ids["alice"]).active = False
        db.commit()
    assert client.get(url(patient, note)).status_code == 401


def test_audit_failure_rolls_back_finalization(setup, monkeypatch):
    from app import sessions
    client, _, _ = setup
    patient = create(client)
    note = saved(client, patient, new_note(client, patient), text="Keep as draft if audit fails")
    def broken_audit(*args):
        raise SQLAlchemyError("Synthetic audit failure")
    with monkeypatch.context() as local:
        local.setattr(sessions, "record_audit", broken_audit)
        assert client.post(url(patient, note) + "/finalize", json={"expectedVersion": note["version"]}).status_code == 503
    current = client.get(url(patient, note)).json()
    assert current["state"] == "draft" and current["version"] == note["version"]


def test_session_creation_after_future_follow_up(setup):
    from app.patients import clinic_today
    client, _, _ = setup
    patient = create(client)
    future = (clinic_today() + timedelta(days=7)).isoformat()
    follow_up = client.post(path(patient) + '/follow-ups', json={'title': 'Synthetic next appointment', 'dueDate': future})
    assert follow_up.status_code == 201
    rejected = client.post(path(patient) + '/sessions', json={'eventDate': future})
    assert rejected.status_code == 422
    assert 'future' in rejected.json()['fieldErrors']['eventDate']
    for event_date in (clinic_today().isoformat(), None):
        note = new_note(client, patient, event_date)
        assert note['state'] == 'draft'
        assert note['eventDate'] == event_date
        assert client.get(url(patient, note)).status_code == 200
    tasks = client.get(path(patient) + '/follow-ups').json()['items']
    assert next(t for t in tasks if t['id'] == follow_up.json()['id'])['dueDate'] == future
