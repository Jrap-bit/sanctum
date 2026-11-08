from datetime import timedelta
from urllib.parse import urlparse, parse_qs

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.manage import create_user
from app.db.models import CredentialToken, User, AuditEvent, now
from app.core.security import COOKIE_NAME, token_digest

PASSWORD = 'Synthetic-password-42'
NEW_PASSWORD = 'Replacement-password-43'
ORIGIN = {'Origin': 'http://localhost:3000'}
ROOT = '/api/v1/admin/users'

@pytest.fixture
def setup():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        admin = create_user(db, 'admin', 'Admin', 'admin', PASSWORD)
        staff = create_user(db, 'staff', 'Staff', 'clinician', PASSWORD)
        ids = admin.id, staff.id
    def dependency():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = dependency
    with TestClient(app) as client:
        assert login(client, 'admin').status_code == 200
        yield client, factory, ids
    app.dependency_overrides.clear()
    engine.dispose()

def login(c, username, password=PASSWORD):
    return c.post('/api/v1/auth/login', headers=ORIGIN, json={'username': username, 'password': password})

def post(c, path, body=None):
    return c.post(path, headers=ORIGIN, json=body or {})

def invite(c, email=None):
    payload = {'username': ' New.Staff ', 'displayName': 'New Staff', 'capabilities': ['patients:read', 'clinical:write']}
    if email is not None:
        payload['email'] = email
    response = post(c, ROOT, payload)
    assert response.status_code == 201, response.text
    data = response.json()
    return data['user']['id'], parse_qs(urlparse(data['credentialAction']['url']).query)['token'][0]

def redeem(c, token):
    return post(c, '/api/v1/auth/activate', {'token': token, 'password': NEW_PASSWORD})

def test_invitation_activation_and_replay(setup):
    c, factory, _ = setup
    uid, token = invite(c)
    assert login(c, 'new.staff').status_code == 401
    with factory() as db:
        assert not db.get(User, uid).active
        assert db.get(CredentialToken, token_digest(token)) is not None
        assert db.get(CredentialToken, token) is None
    c.cookies.clear()
    assert redeem(c, token).status_code == 200
    assert COOKIE_NAME not in c.cookies
    assert redeem(c, token).status_code == 400
    assert login(c, 'new.staff', NEW_PASSWORD).status_code == 200

def test_list_filter_permissions_and_self_protection(setup):
    c, _, (admin, _) = setup
    uid, _ = invite(c)
    items = c.get(ROOT).json()['items']
    assert next(u for u in items if u['id'] == uid)['active'] is False
    assert all(u['active'] for u in c.get(ROOT + '?active=true').json()['items'])
    assert 'password_hash' not in c.get(ROOT).text
    for action in ['deactivate', 'reset-credential']:
        assert post(c, f'{ROOT}/{admin}/{action}').status_code == 409
    login(c, 'staff')
    assert c.get(ROOT).status_code == 403
    assert post(c, ROOT, {'username': 'blocked', 'displayName': 'Blocked', 'capabilities': ['users:manage']}).status_code == 403

@pytest.mark.parametrize('caps', [['unknown'], ['users:manage', 'clinical:write'], ['patients:delete'], []])
def test_disallowed_permissions(setup, caps):
    c, _, _ = setup
    assert post(c, ROOT, {'username': 'baduser', 'displayName': 'Bad', 'capabilities': caps}).status_code == 422

def test_reset_revokes_session_and_password_and_prior_link(setup):
    c, _, (_, staff) = setup
    with TestClient(app) as other:
        assert login(other, 'staff').status_code == 200
        def reset():
            r = post(c, f'{ROOT}/{staff}/reset-credential')
            assert r.status_code == 200
            return parse_qs(urlparse(r.json()['credentialAction']['url']).query)['token'][0]
        old, fresh = reset(), reset()
        assert other.get('/api/v1/auth/me').status_code == 401
        assert login(other, 'staff').status_code == 401
        assert redeem(other, old).status_code == 400
        assert redeem(other, fresh).status_code == 200
        assert login(other, 'staff').status_code == 401
        assert login(other, 'staff', NEW_PASSWORD).status_code == 200

def test_deactivate_preserves_account_and_reactivate_replaces_link(setup):
    c, factory, _ = setup
    uid, old = invite(c)
    assert post(c, f'{ROOT}/{uid}/deactivate').status_code == 200
    assert redeem(c, old).status_code == 400
    result = post(c, f'{ROOT}/{uid}/reactivate').json()
    assert result['user']['active'] is False
    fresh = parse_qs(urlparse(result['credentialAction']['url']).query)['token'][0]
    assert redeem(c, fresh).status_code == 200
    assert post(c, f'{ROOT}/{uid}/deactivate').status_code == 200
    assert post(c, f'{ROOT}/{uid}/reset-credential').status_code == 409
    assert post(c, f'{ROOT}/{uid}/reactivate').json()['user']['active'] is True
    with factory() as db:
        assert db.get(User, uid) is not None
        events = db.scalars(select(AuditEvent).where(AuditEvent.target_id == uid)).all()
        assert {'user.create', 'credential.activation', 'user.deactivate', 'user.reactivate'} <= {e.action for e in events}
        assert all(old not in str(e.__dict__) and PASSWORD not in str(e.__dict__) for e in events)

def test_expired_link_duplicate_and_password_validation(setup):
    c, factory, _ = setup
    _, token = invite(c)
    assert post(c, ROOT, {'username': 'NEW.STAFF', 'displayName': 'Duplicate', 'capabilities': ['patients:read']}).status_code == 409
    assert post(c, '/api/v1/auth/activate', {'token': token, 'password': 'short'}).status_code == 422
    with factory() as db:
        db.get(CredentialToken, token_digest(token)).expires_at = now() - timedelta(seconds=1)
        db.commit()
    expired = redeem(c, token)
    unknown = redeem(c, 'unknown')
    assert expired.status_code == unknown.status_code == 400
    assert expired.json()['message'] == unknown.json()['message']

def test_activation_rate_limit(setup):
    c, _, _ = setup
    for _ in range(30):
        assert redeem(c, 'unknown').status_code == 400
    assert redeem(c, 'unknown').status_code == 429

def test_create_account_email_validation_and_uniqueness(setup):
    c, factory, _ = setup
    # Valid email lowercased and saved
    res = post(c, ROOT, {
        'username': 'doc.smith',
        'displayName': 'Doc Smith',
        'capabilities': ['patients:read'],
        'email': ' Doc.Smith@Example.Com '
    })
    assert res.status_code == 201
    data = res.json()
    assert data['user']['email'] == 'doc.smith@example.com'

    # AdminUserOutput includes email
    items = c.get(ROOT).json()['items']
    smith = next(u for u in items if u['username'] == 'doc.smith')
    assert smith['email'] == 'doc.smith@example.com'

    # Duplicate email returns 409
    dup_res = post(c, ROOT, {
        'username': 'other.smith',
        'displayName': 'Other Smith',
        'capabilities': ['patients:read'],
        'email': 'doc.smith@example.com'
    })
    assert dup_res.status_code == 409

    # Invalid email formats return 422
    for bad_email in ['not-an-email', '@missinguser.com', 'user@', 'user@domain']:
        bad_res = post(c, ROOT, {
            'username': 'bad.user',
            'displayName': 'Bad User',
            'capabilities': ['patients:read'],
            'email': bad_email
        })
        assert bad_res.status_code == 422

def test_manage_create_user_with_email(setup):
    _, factory, _ = setup
    with factory() as db:
        user = create_user(db, 'operator', 'Operator User', 'clinician', PASSWORD, email=' Operator@example.com ')
        assert user.email == 'operator@example.com'
    with pytest.raises(ValueError):
        with factory() as db:
            create_user(db, 'bad_operator', 'Bad Operator', 'clinician', PASSWORD, email='invalid-email')

