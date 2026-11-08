from io import StringIO
import sys
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.adapters.crypto import initialize_key
from app.adapters.crypto import reload_keys
from app.adapters.objectstore import reset_store
from app.core.config import get_settings
from app.core.database import Base
from app.db.models import User
import app.manage as manage_module
import app.smoke as smoke_module


@pytest.fixture
def setup_db(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "master_key", None)
    monkeypatch.setattr(get_settings(), "master_key_path", tmp_path / "master.key")
    monkeypatch.setattr(get_settings(), "wrapped_keys_path", tmp_path / "data-keys.json")
    monkeypatch.setattr(get_settings(), "store_path", tmp_path / "storage" / "objects")
    reload_keys()
    reset_store()
    initialize_key()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    deleted_sessions = []
    monkeypatch.setattr(smoke_module, "delete_user_sessions", lambda uid: deleted_sessions.append(uid))
    factory.deleted_sessions = deleted_sessions
    monkeypatch.setattr(smoke_module, "SessionLocal", factory)
    monkeypatch.setattr(manage_module, "SessionLocal", factory)
    yield factory
    engine.dispose()


def make_transport(fail_step=None, error_step=None):
    state = {
        "patient_id": "patient-123",
        "session_id": "session-456",
        "doc_id": "doc-789",
        "summary_id": "sum-res-1",
        "report_id": "rep-1",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url_path = request.url.path
        method = request.method

        step = None
        if url_path == "/api/v1/health":
            step = "health"
        elif url_path == "/api/v1/auth/login":
            step = "login"
        elif url_path == "/api/v1/patients" and method == "POST":
            step = "scoped write"
        elif "/sessions" in url_path and (method in ("PATCH", "POST")):
            step = "scoped write"
        elif "/sessions" in url_path and method == "GET":
            step = "scoped read"
        elif "/documents" in url_path and method == "POST" and not url_path.endswith("/process") and not url_path.endswith("/confirm"):
            step = "document upload"
        elif url_path.endswith("/process") or url_path == f"/api/v1/patients/{state['patient_id']}/documents" or url_path.endswith("/pages"):
            if method == "PATCH" and "/pages/" in url_path:
                step = "import review"
            else:
                step = "ocr"
        elif url_path.endswith("/confirm") or (method == "PATCH" and "/pages/" in url_path):
            step = "import review"
        elif url_path == f"/api/v1/patients/{state['patient_id']}/summaries" or "/jobs/" in url_path or (url_path == f"/api/v1/patients/{state['patient_id']}/summaries/{state['summary_id']}" and method == "GET"):
            step = "local generation"
        elif url_path.endswith("/review"):
            step = "summary review"
        elif url_path.endswith("/indicators/evaluate"):
            step = "rule evaluation"
        elif "/reports" in url_path:
            step = "report export"

        if error_step and step == error_step:
            raise httpx.ConnectError("Connection refused")

        if fail_step and step == fail_step:
            return httpx.Response(500, json={"error": "Mocked failure"})

        # 1. health
        if url_path == "/api/v1/health":
            return httpx.Response(200, json={"status": "ok"})

        # 2. login
        if url_path == "/api/v1/auth/login":
            headers = [("Set-Cookie", "sanctum_session=mocktoken; Path=/; HttpOnly")]
            return httpx.Response(200, json={"success": True}, headers=headers)

        # 3. scoped write
        if url_path == "/api/v1/patients" and method == "POST":
            return httpx.Response(201, json={"id": state["patient_id"], "displayName": "Smoke Test"})

        if url_path == f"/api/v1/patients/{state['patient_id']}/sessions" and method == "POST":
            return httpx.Response(201, json={"id": state["session_id"], "version": 1})

        if url_path == f"/api/v1/patients/{state['patient_id']}/sessions/{state['session_id']}" and method == "PATCH":
            return httpx.Response(200, json={"id": state["session_id"], "version": 2, "text": "Synthetic smoke test session note sentence."})

        if url_path == f"/api/v1/patients/{state['patient_id']}/sessions/{state['session_id']}/finalize" and method == "POST":
            return httpx.Response(200, json={"id": state["session_id"], "version": 3, "state": "finalized"})

        # 4. scoped read
        if url_path == f"/api/v1/patients/{state['patient_id']}/sessions/{state['session_id']}" and method == "GET":
            cookie = request.headers.get("cookie", "")
            if "sanctum_session" in cookie:
                return httpx.Response(200, json={"id": state["session_id"], "text": "Synthetic smoke test session note sentence."})
            return httpx.Response(401, json={"detail": "Not authenticated"})

        # 5. document upload
        if url_path == f"/api/v1/patients/{state['patient_id']}/documents" and method == "POST":
            return httpx.Response(201, json={"id": state["doc_id"], "pageCount": 1})

        # 6. ocr
        if url_path == f"/api/v1/patients/{state['patient_id']}/documents/{state['doc_id']}/process":
            return httpx.Response(202, json={"id": "job-1"})

        if url_path == f"/api/v1/patients/{state['patient_id']}/documents" and method == "GET":
            return httpx.Response(200, json={"items": [{"id": state["doc_id"], "jobState": "completed"}]})

        if url_path == f"/api/v1/patients/{state['patient_id']}/documents/{state['doc_id']}/pages" and method == "GET":
            return httpx.Response(200, json={"pages": [{"pageNumber": 1, "version": 1, "rawText": "Synthetic smoke test document page."}]})

        # 7. import review
        if url_path == f"/api/v1/patients/{state['patient_id']}/documents/{state['doc_id']}/pages/1" and method == "PATCH":
            return httpx.Response(200, json={"documentVersion": 2})

        if url_path == f"/api/v1/patients/{state['patient_id']}/documents/{state['doc_id']}/confirm" and method == "POST":
            return httpx.Response(200, json={"success": True})

        # 8. local generation
        if url_path == f"/api/v1/patients/{state['patient_id']}/summaries" and method == "POST":
            return httpx.Response(202, json={"id": "job-sum-1"})

        if url_path == "/api/v1/jobs/job-sum-1" and method == "GET":
            return httpx.Response(200, json={"id": "job-sum-1", "state": "completed", "resultId": state["summary_id"]})

        if url_path == f"/api/v1/patients/{state['patient_id']}/summaries/{state['summary_id']}" and method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": state["summary_id"],
                    "version": 1,
                    "text": "Summary generated text.",
                    "evidence": [{"sourceId": state["session_id"], "quote": "Sentence quote"}],
                    "facts": [{"id": "fact-1", "state": "pending", "text": "Fact text"}],
                    "reviewState": "pending",
                },
            )

        # 9. summary review
        if url_path == f"/api/v1/patients/{state['patient_id']}/summaries/{state['summary_id']}/review" and method == "POST":
            return httpx.Response(
                200,
                json={
                    "id": state["summary_id"],
                    "version": 2,
                    "reviewState": "accepted",
                    "facts": [{"id": "fact-1", "state": "pending", "text": "Fact text"}],
                },
            )

        # 10. rule evaluation
        if url_path == f"/api/v1/patients/{state['patient_id']}/indicators/evaluate" and method == "POST":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"id": "ind-1", "outcome": "matched", "ruleVersion": 1},
                        {"id": "ind-2", "outcome": "not_matched", "ruleVersion": 1},
                        {"id": "ind-3", "outcome": "not_evaluable", "ruleVersion": 1},
                    ]
                },
            )

        # 11. report export
        if url_path == f"/api/v1/patients/{state['patient_id']}/reports/preview" and method == "POST":
            return httpx.Response(
                200,
                json={
                    "id": state["report_id"],
                    "included": [
                        {"id": state["summary_id"], "label": "AI summary", "version": 2, "reviewState": "accepted"}
                    ],
                },
            )

        if url_path == f"/api/v1/patients/{state['patient_id']}/reports/{state['report_id']}/export" and method == "GET":
            return httpx.Response(200, content=b"%PDF-1.4 mock report content")

        return httpx.Response(404, json={"detail": f"Unmatched URL {url_path}"})

    return httpx.MockTransport(handler)


def test_smoke_all_success(setup_db):
    factory = setup_db
    transport = make_transport()
    output_lines = []

    result = smoke_module.run(
        base_url="http://127.0.0.1:8000",
        out=output_lines.append,
        poll_interval=0,
        transport=transport,
    )

    assert result is True
    expected_passes = [
        "PASS  health",
        "PASS  login",
        "PASS  scoped write",
        "PASS  scoped read",
        "PASS  document upload",
        "PASS  ocr",
        "PASS  import review",
        "PASS  local generation",
        "PASS  summary review",
        "PASS  rule evaluation",
        "PASS  report export",
    ]
    for expected in expected_passes:
        assert expected in output_lines
    assert output_lines[-1] == "SANCTUM SMOKE TEST PASS"

    # Temporary account is deactivated
    with factory() as db:
        user = db.scalar(select(User).where(User.username.like("smoke_%")))
        assert user is not None
        assert user.active is False
        assert user.id in factory.deleted_sessions
        assert user.id in factory.deleted_sessions


@pytest.mark.parametrize(
    "step_name",
    [
        "health",
        "login",
        "scoped write",
        "scoped read",
        "document upload",
        "ocr",
        "import review",
        "local generation",
        "summary review",
        "rule evaluation",
        "report export",
    ],
)
def test_smoke_failure_at_step_n_stops_there(setup_db, step_name):
    factory = setup_db
    transport = make_transport(fail_step=step_name)
    output_lines = []

    result = smoke_module.run(
        base_url="http://127.0.0.1:8000",
        out=output_lines.append,
        poll_interval=0,
        transport=transport,
    )

    assert result is False
    assert output_lines[-1] == "SANCTUM SMOKE TEST FAIL"
    fail_line = next((line for line in output_lines if line.startswith(f"FAIL  {step_name}:")), None)
    assert fail_line is not None

    # Step list in order
    steps = [
        "health",
        "login",
        "scoped write",
        "scoped read",
        "document upload",
        "ocr",
        "import review",
        "local generation",
        "summary review",
        "rule evaluation",
        "report export",
    ]
    step_index = steps.index(step_name)
    for next_step in steps[step_index + 1:]:
        assert not any(line.startswith(f"PASS  {next_step}") for line in output_lines)
        assert not any(line.startswith(f"FAIL  {next_step}") for line in output_lines)

    # Temporary account is deactivated
    with factory() as db:
        user = db.scalar(select(User).where(User.username.like("smoke_%")))
        assert user is not None
        assert user.active is False
        assert user.id in factory.deleted_sessions
        assert user.id in factory.deleted_sessions


def test_smoke_connection_error_is_fail(setup_db):
    factory = setup_db
    transport = make_transport(error_step="health")
    output_lines = []

    result = smoke_module.run(
        base_url="http://127.0.0.1:8000",
        out=output_lines.append,
        poll_interval=0,
        transport=transport,
    )

    assert result is False
    assert "FAIL  health: connection error" in output_lines
    assert output_lines[-1] == "SANCTUM SMOKE TEST FAIL"

    with factory() as db:
        user = db.scalar(select(User).where(User.username.like("smoke_%")))
        assert user is not None
        assert user.active is False
        assert user.id in factory.deleted_sessions


def test_smoke_setup_failure(monkeypatch):
    monkeypatch.setattr(smoke_module, "SessionLocal", lambda: (_ for _ in ()).throw(RuntimeError("DB down")))
    output_lines = []
    result = smoke_module.run(out=output_lines.append)
    assert result is False
    assert "FAIL  setup: database unavailable" in output_lines
    assert output_lines[-1] == "SANCTUM SMOKE TEST FAIL"


def test_smoke_manage_command_exit_codes(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["manage.py", "smoke-test"])

    # Success case exits 0
    monkeypatch.setattr(smoke_module, "run", lambda *args, **kwargs: True)
    with pytest.raises(SystemExit) as exc:
        manage_module.main()
    assert exc.value.code == 0

    # Failure case exits 1
    monkeypatch.setattr(smoke_module, "run", lambda *args, **kwargs: False)
    with pytest.raises(SystemExit) as exc:
        manage_module.main()
    assert exc.value.code == 1

    # Custom --base-url is passed to run
    called_url = []
    monkeypatch.setattr(sys, "argv", ["manage.py", "smoke-test", "--base-url", "http://custom-host:9000"])
    monkeypatch.setattr(smoke_module, "run", lambda base_url, *args, **kwargs: called_url.append(base_url) or True)
    with pytest.raises(SystemExit) as exc:
        manage_module.main()
    assert exc.value.code == 0
    assert called_url == ["http://custom-host:9000"]
