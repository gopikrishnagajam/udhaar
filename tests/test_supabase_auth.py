"""Supabase is simulated at the HTTP boundary; no test sends real email."""
import json
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
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
    state = {'requests': [], 'users': {}, 'tokens': {}, 'refresh': {}, 'expired': set(), 'offline': False, 'otp_failure': None, 'clock': 1000}
    private_key = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(auth, '_clock', lambda: state['clock'])
    monkeypatch.setattr(auth, 'signing_keys', lambda url: SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=private_key.public_key())))
    def mint(user, **changes):
        claims = {'sub': user['id'], 'iss': 'https://test-project.supabase.co/auth/v1',
                  'aud': 'authenticated', 'role': 'authenticated', 'is_anonymous': False,
                  'iat': int(time.time()), 'exp': int(time.time()) + 3600, 'jti': str(uuid4())}
        claims.update(changes)
        return jwt.encode(claims, private_key, algorithm='ES256', headers={'kid': 'test-key'})
    state['mint'] = mint

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
                return httpx.Response(state.get('otp_status', 500), json=state['otp_failure'], headers=state.get('otp_headers', {}))
            return httpx.Response(200, json={})
        if path.endswith('/verify'):
            if payload['token'] != '123456':
                return httpx.Response(403, json={'msg': 'Invalid OTP'})
            email = payload['email']
            user = state['users'].setdefault(email, {'id': str(uuid4()), 'email': email, 'email_confirmed_at': '2026-10-16T00:00:00Z'})
            access, refresh = mint(user), 'refresh-' + user['id']
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
            access, refresh = mint(user), 'renewed-refresh-' + str(uuid4())
            state['tokens'][access] = user
            state['refresh'][refresh] = user
            return httpx.Response(200, json={'access_token': access, 'refresh_token': refresh, 'expires_in': 3600})
        if path.endswith('/logout'):
            assert request.url.params['scope'] == 'local'
            token = request.headers.get('authorization', '').removeprefix('Bearer ')
            if token not in state['tokens'] or token in state['expired']:
                return httpx.Response(403, json={'error_code': 'bad_jwt', 'msg': 'Invalid or expired JWT'})
            return httpx.Response(204)
        raise AssertionError('Unexpected provider endpoint')

    original_client = httpx.Client
    monkeypatch.setattr(auth.httpx, 'Client', lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    yield setup, state
    auth._attempts.clear()


def signin(client, email='alex@example.com', name='Alex', signup=True):
    requested = post(client, '/api/auth/otp', {'email': email, 'signup': signup})
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
    (owner, guest, _), state = remote
    first = signin(owner).json()['id']
    record = post(owner, '/api/records', {'direction': 'LENT', 'contact_name': 'Rahul', 'item_name': 'Book', 'loan_date': '2026-10-16'})
    assert record.status_code == 201
    state['clock'] += 61
    assert signin(owner, name='Other name', signup=False).json()['id'] == first
    signin(guest, 'sam@example.com', 'Sam')
    assert guest.get('/api/records').json() == []
    assert guest.get('/api/records/' + record.json()['id']).status_code == 404


def test_expired_access_refreshes_and_rotates_cookies(remote):
    (owner, _, _), state = remote
    signin(owner)
    old = owner.cookies.get(auth.ACCESS_COOKIE)
    owner.cookies.set(auth.ACCESS_COOKIE, state['mint'](state['users']['alex@example.com'], exp=int(time.time())-1), domain='testserver.local', path='/')
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


def test_provider_outage_does_not_interrupt_locally_validated_requests(remote):
    (owner, _, _), state = remote
    signin(owner)
    state['offline'] = True
    assert owner.get('/api/me').status_code == 200
    state['clock'] += 61
    assert post(owner, '/api/auth/otp', {'email': 'alex@example.com'}).status_code == 503


@pytest.mark.parametrize('valid_refresh', [True, False])
def test_logout_retries_rejected_access_with_refresh_and_always_clears_cookies(remote, valid_refresh):
    (owner, _, _), state = remote
    signin(owner)
    expired = state['mint'](state['users']['alex@example.com'], exp=int(time.time()) - 10)
    owner.cookies.set(auth.ACCESS_COOKIE, expired, domain='testserver.local', path='/')
    state['expired'].add(expired)
    if not valid_refresh:
        state['refresh'].clear()
    state['requests'].clear()

    result = post(owner, '/api/auth/logout')

    assert result.status_code == 200
    assert result.json()['provider_session_revoked'] is valid_refresh
    assert [request[1] for request in state['requests']] == (
        ['/auth/v1/logout', '/auth/v1/token', '/auth/v1/logout'] if valid_refresh
        else ['/auth/v1/logout', '/auth/v1/token'])
    assert not owner.cookies.get(auth.ACCESS_COOKIE)
    assert not owner.cookies.get(auth.REFRESH_COOKIE)
    assert owner.get('/api/me').status_code == 401
    # A refresh performed only for logout must never issue new browser tokens.
    assert all('Max-Age=0' in value for value in result.headers.get_list('set-cookie'))


def test_logout_uses_refresh_when_access_cookie_has_expired_from_browser(remote):
    (owner, _, _), state = remote
    signin(owner)
    owner.cookies.delete(auth.ACCESS_COOKIE)
    state['requests'].clear()
    result = post(owner, '/api/auth/logout')
    assert result.json()['provider_session_revoked'] is True
    assert [request[1] for request in state['requests']] == ['/auth/v1/token', '/auth/v1/logout']
    assert not owner.cookies.get(auth.REFRESH_COOKIE)


def test_logout_outage_does_not_trigger_a_refresh_retry(remote):
    (owner, _, _), state = remote
    signin(owner)
    state['offline'] = True
    state['requests'].clear()
    result = post(owner, '/api/auth/logout')
    assert result.json()['provider_session_revoked'] is False
    assert [request[1] for request in state['requests']] == ['/auth/v1/logout']
    assert not owner.cookies.get(auth.ACCESS_COOKIE)
    assert not owner.cookies.get(auth.REFRESH_COOKIE)


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


def test_unverified_identity_cannot_establish_a_session(remote):
    (owner, _, _), state = remote
    state['users']['alex@example.com'] = {'id': str(uuid4()), 'email': 'alex@example.com', 'email_confirmed_at': None}
    assert post(owner, '/api/auth/verify', {'email': 'alex@example.com', 'code': '123456'}).status_code == 401


def test_otp_rate_limit_and_configuration_failure(remote, monkeypatch):
    (owner, _, _), state = remote
    for index in range(5):
        assert post(owner, '/api/auth/otp', {'email': f'user{index}@example.com'}).status_code == 200
    assert post(owner, '/api/auth/otp', {'email': 'alex@example.com'}).status_code == 429
    monkeypatch.delenv('SUPABASE_PUBLISHABLE_KEY')
    assert owner.get('/api/auth/config').json()['configured'] is False
    assert post(owner, '/api/auth/otp', {'email': 'alex@example.com'}).status_code == 503


def test_existing_signup_sends_no_email_and_does_not_block_signin(remote):
    (owner, _, _), state = remote
    original_id = signin(owner).json()['id']
    state['clock'] += 61
    state['requests'].clear()
    response = post(owner, '/api/auth/otp', {'email': '  ALEX@EXAMPLE.COM  ', 'signup': True})
    assert response.status_code == 409
    assert 'Sign in instead' in response.json()['detail']
    assert state['requests'] == []
    assert signin(owner, signup=False).json()['id'] == original_id


def test_email_cooldown_is_shared_between_forms_and_returns_actual_wait(remote):
    (owner, guest, _), state = remote
    assert post(owner, '/api/auth/otp', {'email': 'alex@example.com', 'signup': True}).status_code == 200
    state['clock'] += 10
    blocked = post(guest, '/api/auth/otp', {'email': 'ALEX@example.com', 'signup': False})
    assert blocked.status_code == 429
    assert blocked.headers['retry-after'] == '50'
    assert len(state['requests']) == 1
    state['clock'] += 50
    assert post(guest, '/api/auth/otp', {'email': 'alex@example.com'}).status_code == 200
    assert len(state['requests']) == 2


def test_normal_app_requests_do_not_consume_supabase_user_endpoint_limit(remote):
    (owner, _, _), state = remote
    signin(owner)
    baseline = len(state['requests'])
    for _ in range(35):
        assert owner.get('/api/me').status_code == 200
        assert owner.get('/api/records').status_code == 200
    assert len(state['requests']) == baseline


@pytest.mark.parametrize('claims', [
    {'exp': 1}, {'iss': 'https://wrong-project.supabase.co/auth/v1'},
    {'aud': 'wrong-audience'}, {'sub': 'invalid-uuid'},
    {'role': 'service_role'}, {'is_anonymous': True},
    {'iat': int(time.time()) + 3600}, {'nbf': int(time.time()) + 3600},
])
def test_local_token_validation_rejects_invalid_claims(remote, claims):
    (owner, _, _), state = remote
    signin(owner)
    token = state['mint'](state['users']['alex@example.com'], **claims)
    owner.cookies.set(auth.ACCESS_COOKIE, token, domain='testserver.local', path='/')
    assert owner.get('/api/me').status_code == 401


def test_local_token_validation_rejects_forged_signatures(remote):
    (owner, _, _), state = remote
    signin(owner)
    token = owner.cookies.get(auth.ACCESS_COOKIE)
    claims = jwt.decode(token, options={'verify_signature': False})
    forged = jwt.encode(claims, ec.generate_private_key(ec.SECP256R1()), algorithm='ES256', headers={'kid': 'test-key'})
    owner.cookies.set(auth.ACCESS_COOKIE, forged, domain='testserver.local', path='/')
    assert owner.get('/api/me').status_code == 401


def test_upstream_rate_limit_keeps_provider_retry_after(remote):
    (owner, _, _), state = remote
    state.update(otp_status=429, otp_headers={'Retry-After': '120'}, otp_failure={'error_code': 'over_email_send_rate_limit', 'msg': 'Email rate limit exceeded'})
    result = post(owner, '/api/auth/otp', {'email': 'alex@example.com'})
    assert result.status_code == 429
    assert result.headers['retry-after'] == '120'
    assert 'Supabase' in result.json()['detail']


def test_auth_config_reports_cookie_presence_without_provider_requests(remote):
    (owner, _, _), state = remote
    assert owner.get('/api/auth/config').json()['has_session'] is False
    signin(owner)
    baseline = len(state['requests'])
    assert owner.get('/api/auth/config').json()['has_session'] is True
    assert len(state['requests']) == baseline


def test_anonymous_loan_link_still_supports_both_acknowledgments(remote, mail):
    (owner, guest, _), _state = remote
    signin(owner)
    record = post(owner, '/api/records', {'direction': 'BORROWED', 'mode': 'ON', 'contact_name': 'Rahul', 'contact_email': 'rahul@example.com', 'item_name': 'Book', 'quantity': 1, 'loan_date': '2026-10-16'}).json()
    import re
    path = re.search(r'https://udhaar.example.com(/share/\S+)', mail[-1]['message']).group(1)
    assert guest.get('/api/me').status_code == 401
    assert post(guest, '/api' + path + '/respond', {'accept': True}).status_code == 200
    proposed = post(owner, f"/api/records/{record['id']}/returns", {'quantity': 1}).json()
    assert post(guest, '/api' + path + f"/returns/{proposed['id']}/confirm").status_code == 200
    result = guest.get('/api' + path).json()
    assert result['handover_acknowledgment'] == 'CONFIRMED'
    assert result['return_acknowledgment'] == 'CONFIRMED'
