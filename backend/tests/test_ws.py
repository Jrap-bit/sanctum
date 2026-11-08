from uuid import uuid4
import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.cache import publish_progress
from app.services.session_store import create_ws_ticket
from test_patients import setup, create, path, sign_in
from test_documents import upload


def prepare_job(c):
    p = create(c)
    d = upload(c, p).json()
    base = path(p) + '/documents/' + d['id']
    resp = c.post(base + '/process', json={})
    assert resp.status_code == 202
    job_id = resp.json()['id']
    return p, d, job_id


def test_ws_bad_origin(setup):
    c, _, _ = setup
    _, _, job_id = prepare_job(c)
    with pytest.raises(WebSocketDisconnect) as exc:
        with c.websocket_connect(f'/api/v1/ws/jobs/{job_id}', headers={'origin': 'http://evil.com'}):
            pass
    assert exc.value.code == 4403


def test_ws_no_session(setup):
    c, _, _ = setup
    _, _, job_id = prepare_job(c)
    # New client or clear cookies
    c.cookies.clear()
    with pytest.raises(WebSocketDisconnect) as exc:
        with c.websocket_connect(f'/api/v1/ws/jobs/{job_id}', headers={'origin': 'http://localhost:3000'}):
            pass
    assert exc.value.code == 4401


def test_ws_unknown_job(setup):
    c, _, _ = setup
    prepare_job(c)
    unknown_id = str(uuid4())
    with pytest.raises(WebSocketDisconnect) as exc:
        with c.websocket_connect(f'/api/v1/ws/jobs/{unknown_id}', headers={'origin': 'http://localhost:3000'}):
            pass
    assert exc.value.code == 4404


def test_ws_no_patient_access(setup):
    c, _, _ = setup
    _, _, job_id = prepare_job(c)
    sign_in(c, 'bob')
    with pytest.raises(WebSocketDisconnect) as exc:
        with c.websocket_connect(f'/api/v1/ws/jobs/{job_id}', headers={'origin': 'http://localhost:3000'}):
            pass
    assert exc.value.code == 4404


def test_ws_ticket_works_once(setup):
    c, _, ids = setup
    _, _, job_id = prepare_job(c)
    alice_id = ids['alice']
    ticket = create_ws_ticket(alice_id)
    c.cookies.clear()

    # First connection with ticket succeeds
    with c.websocket_connect(f'/api/v1/ws/jobs/{job_id}?ticket={ticket}', headers={'origin': 'http://localhost:3000'}) as ws:
        msg = ws.receive_json()
        assert msg['jobId'] == str(job_id)

    # Re-using the consumed ticket fails with 4401
    with pytest.raises(WebSocketDisconnect) as exc:
        with c.websocket_connect(f'/api/v1/ws/jobs/{job_id}?ticket={ticket}', headers={'origin': 'http://localhost:3000'}):
            pass
    assert exc.value.code == 4401


def test_ws_progress_and_terminal_close(setup):
    c, _, _ = setup
    _, _, job_id = prepare_job(c)
    with c.websocket_connect(f'/api/v1/ws/jobs/{job_id}', headers={'origin': 'http://localhost:3000'}) as ws:
        init_state = ws.receive_json()
        assert init_state['state'] == 'queued'

        publish_progress(job_id, state='running', progress=50, stage='Page 1 of 2')
        progress_evt = ws.receive_json()
        assert progress_evt['state'] == 'running'
        assert progress_evt['progress'] == 50
        assert progress_evt['stage'] == 'Page 1 of 2'

        publish_progress(job_id, state='completed', progress=100, message='Finished')
        term_evt = ws.receive_json()
        assert term_evt['state'] == 'completed'

        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1000
