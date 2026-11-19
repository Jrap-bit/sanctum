"""Unit tests for smoke-test runner failures and the manage command exit codes."""
import sys
import pytest
import app.manage as manage_module
import app.smoke as smoke_module


@pytest.mark.unit
def test_smoke_setup_failure(monkeypatch):
    monkeypatch.setattr(smoke_module, "SessionLocal", lambda: (_ for _ in ()).throw(RuntimeError("DB down")))
    output_lines = []
    result = smoke_module.run(out=output_lines.append)
    assert result is False
    assert "FAIL  setup: database unavailable" in output_lines
    assert output_lines[-1] == "SANCTUM SMOKE TEST FAIL"


@pytest.mark.unit
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
