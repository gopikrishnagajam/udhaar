"""Supabase is simulated at the HTTP boundary; no test sends real email."""
import json
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, func

from backend import supabase_auth as auth
from backend.main import app, get_db
from backend.models import AuthIdentity, LoginSession, User


def post(client, path, payload=None):
    return client.post(path, json=payload or {}, headers={'X-CSRF-Token': client.cookies.get('udhaar_csrf', '')})


@pytest.fixture
def remote(setup, monkeypatch):
    monkeypatch.setenv('UDHAAR_AUTH_PROVIDER', 'supabase')
    monkeypatch.setenv('SUPABASE_URL', 'https://test-project.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'sb_publishable_test')
    auth._attempts.clear()
    state = {'requests': [], 'users': {}, 'tokens': {}, 'refresh': {}, 'expired': set(), 'offline': False, 'otp_failure': None}

    def handler(request):
        assert str(request.url).startswith('https://test-project.supabase.co/auth/v1/')
        assert request.headers['apikey'] == 'sb_publishable_test'
        payload = json.loads(request.content) if request.content else {}
        state['requests'].append((request.method, request.url.path, payload))
        if state['offline']:
            raise httpx.ConnectError('offline', request=request)
        path = request.url.path
        if path.endswith('/otp'):
            if state['otp_failure']:
                return httpx.Response(500, json=state['otp_failure'])
            return httpx.Response(200, json={})
        if path.endswith('/verify'):
            if payload['token'] != '123456':
                return httpx.Response(403, json={'msg': 'Invalid OTP'})
            email = payload['email']
            user = state['users'].setdefault(email, {'id': str(uuid4()), 'email': email, 'email_confirmed_at': '2026-10-16T00:00:00Z'})
            access, refresh = 'access-' + user['id'], 'refresh-' + user['id']
            state['tokens'][access] = user
            state['refresh'][refresh] = user
            return httpx.Response(200, json={'access_token': access, 'refresh_token': refresh, 'expires_in': 3600})
        if path.endswith('/user'):
            token = request.headers.get('authorization', '').removeprefix('Bearer ')
            user = state['tokens'].get(token)
            return httpx.Response(200, json=user) if user and token not in state['expired'] else httpx.Response(401, json={})
        if path.endswith('/token'):
            assert request.url.params['grant_type'] == 'refresh_token'
            user = state['refresh'].pop(payload['refresh_token'], None)
            if not user:
                return httpx.Response(401, json={})
            access, refresh = 'renewed-' + str(uuid4()), 'renewed-refresh-' + str(uuid4())
            state['tokens'][access] = user
            state['refresh'][refresh] = user
            return httpx.Response(200, json={'access_token': access, 'refresh_token': refresh, 'expires_in': 3600})
        if path.endswith('/logout'):
            assert request.url.params['scope'] == 'local'
            return httpx.Response(204)
        raise AssertionError('Unexpected provider endpoint')

    original_client = httpx.Client
    monkeypatch.setattr(auth.httpx, 'Client', lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    yield setup, state
    auth._attempts.clear()


def signin(client, email='alex@example.com', name='Alex'):
    requested = post(client, '/api/auth/otp', {'email': email, 'signup': True})
    assert requested.status_code == 200, requested.text
    response = post(client, '/api/auth/verify', {'email': email, 'code': '123456', 'name': name})
    assert response.status_code == 200, response.text
    return response


def test_verified_otp_creates_local_profile_without_password_or_tokens(remote):
    (owner, _, _), state = remote
    response = signin(owner)
    assert 'access_token' not in response.text and 'refresh_token' not in response.text
    cookies = response.headers.get_list('set-cookie')
    assert any('udhaar_sb_access=' in value and 'HttpOnly' in value and 'SameSite=lax' in value for value in cookies)
    assert any('udhaar_sb_refresh=' in value and 'HttpOnly' in value and 'Path=/api/auth' in value for value in cookies)
    assert state['requests'][0][2] == {'email': 'alex@example.com', 'create_user': True}
    assert owner.get('/api/me').json()['name'] == 'Alex'
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        user = db.scalar(select(User))
        identity = db.scalar(select(AuthIdentity))
        assert user.password_hash == ''
        assert identity.user_id == user.id
        assert identity.subject == state['users']['alex@example.com']['id']
        assert db.scalar(select(func.count()).select_from(LoginSession)) == 0
    finally:
        db.close()


def test_profile_is_stable_on_repeat_signin_and_accounts_are_isolated(remote):
    (owner, guest, _), _state = remote
    first = signin(owner).json()['id']
    record = post(owner, '/api/records', {'direction': 'LENT', 'contact_name': 'Rahul', 'item_name': 'Book', 'loan_date': '2026-10-16'})
    assert record.status_code == 201
    assert signin(owner, name='Other name').json()['id'] == first
    signin(guest, 'sam@example.com', 'Sam')
    assert guest.get('/api/records').json() == []
    assert guest.get('/api/records/' + record.json()['id']).status_code == 404


def test_expired_access_refreshes_and_rotates_cookies(remote):
    (owner, _, _), state = remote
    signin(owner)
    old = owner.cookies.get(auth.ACCESS_COOKIE)
    state['expired'].add(old)
    assert owner.get('/api/me').status_code == 401
    assert post(owner, '/api/auth/refresh').status_code == 200
    assert owner.cookies.get(auth.ACCESS_COOKIE) != old
    assert owner.get('/api/me').status_code == 200


def test_invalid_codes_and_missing_csrf_do_not_create_accounts(remote):
    (owner, _, _), _state = remote
    assert owner.post('/api/auth/otp', json={'email': 'alex@example.com'}).status_code == 403
    assert post(owner, '/api/auth/verify', {'email': 'alex@example.com', 'code': '654321'}).status_code == 401
    assert owner.get('/api/me').status_code == 401


def test_legacy_password_and_session_cannot_bypass_supabase(remote):
    (owner, _, _), _state = remote
    owner.cookies.set('udhaar_session', 'old-session')
    assert owner.get('/api/me').status_code == 401
    payload = {'name': 'Alex', 'email': 'alex@example.com', 'password': 'StrongPass123!'}
    assert post(owner, '/api/register', payload).status_code == 403
    assert post(owner, '/api/login', payload).status_code == 403


@pytest.mark.parametrize('path', ['/otp', '/verify', '/refresh', '/logout'])
def test_all_authentication_mutations_require_csrf(remote, path):
    (owner, _, _), _state = remote
    response = owner.post('/api/auth' + path, json={'email': 'alex@example.com', 'code': '123456'})
    assert response.status_code == 403


def test_malformed_provider_session_does_not_provision_a_user(remote, monkeypatch):
    (owner, _, _), _state = remote
    original = auth.auth_request
    def missing_refresh(method, path, payload=None, token=None):
        result = original(method, path, payload, token)
        if path == '/verify':
            result.pop('refresh_token')
        return result
    monkeypatch.setattr(auth, 'auth_request', missing_refresh)
    response = post(owner, '/api/auth/verify', {'email': 'alex@example.com', 'code': '123456'})
    assert response.status_code == 503
    assert not owner.cookies.get(auth.ACCESS_COOKIE)
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    assert db.scalar(select(func.count()).select_from(User)) == 0
    db.close()


def test_secure_cookie_configuration(remote, monkeypatch):
    (owner, _, _), _state = remote
    monkeypatch.setenv('UDHAAR_COOKIE_SECURE', 'true')
    response = signin(owner)
    assert all('Secure' in value for value in response.headers.get_list('set-cookie') if 'udhaar_sb_' in value)


def test_legacy_email_collision_requires_explicit_migration(remote):
    (owner, _, _), state = remote
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    db.add(User(name='Legacy owner', email='alex@example.com', password_hash='legacy-hash'))
    db.commit()
    db.close()
    response = post(owner, '/api/auth/verify', {'email': 'alex@example.com', 'code': '123456'})
    assert response.status_code == 409
    assert not owner.cookies.get(auth.ACCESS_COOKIE)
    assert owner.get('/api/me').status_code == 401


@pytest.mark.parametrize('offline', [False, True])
def test_logout_clears_browser_even_when_provider_is_offline(remote, offline):
    (owner, _, _), state = remote
    signin(owner)
    state['offline'] = offline
    result = post(owner, '/api/auth/logout')
    assert result.status_code == 200
    assert result.json()['provider_session_revoked'] is not offline
    assert not owner.cookies.get(auth.ACCESS_COOKIE)
    assert not owner.cookies.get(auth.REFRESH_COOKIE)
    assert owner.get('/api/me').status_code == 401


def test_provider_outage_has_no_local_fallback(remote):
    (owner, _, _), state = remote
    signin(owner)
    state['offline'] = True
    assert owner.get('/api/me').status_code == 503
    assert post(owner, '/api/auth/otp', {'email': 'alex@example.com'}).status_code == 503


def test_email_delivery_failure_is_actionable_without_leaking_provider_details(remote, caplog):
    (owner, _, _), state = remote
    state['otp_failure'] = {'error_code': 'unexpected_failure', 'msg': 'Error sending confirmation email: SMTP password SECRET_SMTP_VALUE for private@example.com'}
    response = post(owner, '/api/auth/otp', {'email': 'alex@example.com'})
    assert response.status_code == 503
    assert 'SMTP settings' in response.json()['detail']
    assert 'upstream_status=500' in caplog.text
    assert 'error_code=unexpected_failure' in caplog.text
    assert 'SECRET_SMTP_VALUE' not in caplog.text + response.text
    assert 'private@example.com' not in caplog.text + response.text


def test_unverified_or_anonymous_identity_is_rejected(remote):
    (owner, _, _), state = remote
    signin(owner)
    state['users']['alex@example.com']['email_confirmed_at'] = None
    assert owner.get('/api/me').status_code == 401


def test_otp_rate_limit_and_configuration_failure(remote, monkeypatch):
    (owner, _, _), state = remote
    for _ in range(5):
        assert post(owner, '/api/auth/otp', {'email': 'alex@example.com'}).status_code == 200
    assert post(owner, '/api/auth/otp', {'email': 'alex@example.com'}).status_code == 429
    monkeypatch.delenv('SUPABASE_PUBLISHABLE_KEY')
    assert owner.get('/api/auth/config').json()['configured'] is False
    assert post(owner, '/api/auth/otp', {'email': 'alex@example.com'}).status_code == 503


def test_anonymous_loan_link_still_supports_both_acknowledgments(remote):
    (owner, guest, _), _state = remote
    signin(owner)
    record = post(owner, '/api/records', {'direction': 'BORROWED', 'mode': 'ON', 'contact_name': 'Rahul', 'item_name': 'Book', 'quantity': 1, 'loan_date': '2026-10-16'}).json()
    path = post(owner, f"/api/records/{record['id']}/share").json()['path']
    assert guest.get('/api/me').status_code == 401
    assert post(guest, '/api' + path + '/respond', {'accept': True}).status_code == 200
    proposed = post(owner, f"/api/records/{record['id']}/returns", {'quantity': 1}).json()
    assert post(guest, '/api' + path + f"/returns/{proposed['id']}/confirm").status_code == 200
    result = guest.get('/api' + path).json()
    assert result['handover_acknowledgment'] == 'CONFIRMED'
    assert result['return_acknowledgment'] == 'CONFIRMED'
