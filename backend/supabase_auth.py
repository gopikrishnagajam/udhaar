"""Server-side Supabase email OTP integration. No provider tokens reach JavaScript."""
import os
import logging
import re
import time
import math
from functools import lru_cache
from collections import OrderedDict
from threading import Lock
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import AuthIdentity, User

ACCESS_COOKIE = 'udhaar_sb_access'
REFRESH_COOKIE = 'udhaar_sb_refresh'
_attempts = OrderedDict()
_attempts_lock = Lock()
logger = logging.getLogger('uvicorn.error')
_clock = time.monotonic


@lru_cache(maxsize=4)
def signing_keys(url):
    # Only public keys are fetched. Cache the key set for at most ten minutes.
    return jwt.PyJWKClient(url + '/auth/v1/.well-known/jwks.json',
                          cache_keys=False, lifespan=600, timeout=5)


def token_subject(access_token):
    """Verify signature and claims locally; no /user call during ordinary app use."""
    url, _ = settings()
    try:
        algorithm = jwt.get_unverified_header(access_token).get('alg')
        if algorithm not in {'ES256', 'RS256'}:
            raise jwt.InvalidAlgorithmError('Unsupported signing algorithm')
        key = signing_keys(url).get_signing_key_from_jwt(access_token)
        claims = jwt.decode(access_token, key.key, algorithms=['ES256', 'RS256'],
                            audience='authenticated', issuer=url + '/auth/v1',
                            options={'require': ['exp', 'iat', 'sub', 'iss', 'aud']})
        if claims.get('role') != 'authenticated' or claims.get('is_anonymous') is not False:
            raise jwt.InvalidTokenError('Verified account required')
        return str(UUID(claims['sub']))
    except jwt.PyJWKClientConnectionError:
        raise HTTPException(503, 'Authentication signing keys unavailable; please retry') from None
    except (jwt.PyJWTError, ValueError, TypeError, AttributeError):
        raise HTTPException(401, 'Session invalid or expired; please sign in again') from None


def provider():
    value = os.getenv('UDHAAR_AUTH_PROVIDER', 'local').strip().lower()
    if value not in {'local', 'supabase'}:
        raise HTTPException(503, 'Invalid authentication provider configuration')
    return value


def settings():
    url = os.getenv('SUPABASE_URL', '').strip().rstrip('/')
    key = os.getenv('SUPABASE_PUBLISHABLE_KEY', '').strip()
    parsed = urlsplit(url)
    if (not key or key.startswith('sb_secret_') or parsed.scheme != 'https' or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path):
        raise HTTPException(503, 'Configure SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY in .env, then recreate the app container')
    return url, key


def require_supabase():
    if provider() != 'supabase':
        raise HTTPException(404, 'Supabase authentication is not enabled')
    settings()


def auth_request(method, path, payload=None, token=None):
    """Call only the configured provider; do not relay sensitive provider errors."""
    url, key = settings()
    headers = {'apikey': key}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    try:
        timeout = httpx.Timeout(30 if path == '/otp' else 10, connect=5)
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            result = client.request(method, url + '/auth/v1' + path, json=payload, headers=headers)
    except httpx.RequestError as exc:
        # Never log exception text: it may include URLs, headers or credentials.
        logger.warning('Supabase auth request failed: endpoint=%s transport=%s', path.split('?')[0], type(exc).__name__)
        if path == '/otp' and isinstance(exc, httpx.TimeoutException):
            raise HTTPException(503, 'The sign-in email request timed out. Wait before requesting another code') from None
        raise HTTPException(503, 'Authentication service unavailable; please retry') from None
    if not 200 <= result.status_code < 300:
        try:
            error = result.json()
        except ValueError:
            error = {}
        if not isinstance(error, dict):
            error = {}
        code = error.get('error_code', error.get('code', 'unknown'))
        code = code if isinstance(code, str) and re.fullmatch(r'[a-z_]{1,80}', code) else 'unknown'
        logger.warning('Supabase auth rejected request: endpoint=%s upstream_status=%s error_code=%s', path.split('?')[0], result.status_code, code)
        message = str(error.get('msg', error.get('message', ''))).lower()
        if path == '/otp' and result.status_code >= 500 and ('sending' in message and ('email' in message or 'mail' in message)):
            raise HTTPException(503, 'Could not send the sign-in email. The app administrator should check SMTP settings and Supabase Auth logs')
        if path == '/otp' and code == 'email_address_not_authorized':
            raise HTTPException(503, 'Email delivery is not enabled for this recipient. Configure custom SMTP in Supabase')
    if result.status_code == 429:
        # Provider cooldowns can be project-wide and longer than the local timer.
        retry = result.headers.get('retry-after', '')
        headers = {'Retry-After': retry} if retry.isdigit() and 0 < int(retry) <= 86400 else {}
        raise HTTPException(429, 'Supabase authentication limit reached. Wait before retrying; check the project Auth rate limits if it persists', headers=headers)
    if result.status_code in {400, 401, 403, 422}:
        raise HTTPException(401, 'Authentication failed. Check your code or sign in again')
    if not 200 <= result.status_code < 300:
        raise HTTPException(503, 'Authentication service unavailable or misconfigured')
    if result.status_code == 204 or not result.content:
        return {}
    try:
        data = result.json()
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except ValueError:
        raise HTTPException(503, 'Invalid authentication service response') from None


def verified_identity(access_token):
    """Supabase /user verifies the access token. Never trust a decoded JWT alone."""
    data = auth_request('GET', '/user', token=access_token)
    try:
        subject = str(UUID(data['id']))
        email = data['email'].strip().casefold()
        if not email or '@' not in email or len(email) > 255 or not data.get('email_confirmed_at') or data.get('is_anonymous'):
            raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(401, 'A verified email account is required') from None
    return subject, email


def find_user(db, subject):
    url, _ = settings()
    identity = db.scalar(select(AuthIdentity).where(AuthIdentity.issuer == url + '/auth/v1', AuthIdentity.subject == subject))
    return db.get(User, identity.user_id) if identity else None


def provision_user(db, subject, email, name):
    user = find_user(db, subject)
    if user:
        # Identity is stable; never reassociate loans by a changed email address.
        return user
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, 'This email belongs to an existing local account. Account migration is required; use a different email for testing')
    # An unusable password preserves the existing schema; OTP users have no local password.
    user = User(name=name or email.split('@')[0][:100], email=email, password_hash='')
    url, _ = settings()
    try:
        db.add(user)
        db.flush()
        db.add(AuthIdentity(issuer=url + '/auth/v1', subject=subject, user_id=user.id))
        db.commit()
    except IntegrityError:
        db.rollback()
        user = find_user(db, subject)
        if not user:
            raise HTTPException(409, 'Account could not be linked; contact support') from None
    return user


def authenticated_user(request, db):
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise HTTPException(401, 'Please sign in')
    subject = token_subject(token)
    user = find_user(db, subject)
    if not user:
        raise HTTPException(401, 'Local account not found; sign in again')
    return user


def set_session(response, session):
    try:
        access = session['access_token']
        refresh = session['refresh_token']
        expires = int(session['expires_in'])
        if not isinstance(access, str) or not isinstance(refresh, str) or not access or not refresh or expires <= 0:
            raise ValueError()
    except (KeyError, ValueError, TypeError):
        raise HTTPException(503, 'Invalid authentication session response') from None
    secure = os.getenv('UDHAAR_COOKIE_SECURE') == 'true'
    response.set_cookie(ACCESS_COOKIE, access, httponly=True, secure=secure, samesite='lax', path='/', max_age=expires)
    # A browser persistence cap; Supabase remains the authority for token validity.
    response.set_cookie(REFRESH_COOKIE, refresh, httponly=True, secure=secure, samesite='lax', path='/api/auth', max_age=14*24*3600)
    response.delete_cookie('udhaar_session', path='/')


def clear_session(response):
    response.delete_cookie(ACCESS_COOKIE, path='/')
    response.delete_cookie(REFRESH_COOKIE, path='/api/auth')
    response.delete_cookie('udhaar_session', path='/')


def limit_attempts(request, email, action):
    """Bounded, process-local protection for the local beta, not a distributed limiter."""
    clock = _clock()
    keys = [(action, 'ip', request.client.host if request.client else 'unknown'), (action, 'email', email)]
    with _attempts_lock:
        for key in keys:
            attempts = [t for t in _attempts.get(key, []) if clock - t < 60]
            _attempts[key] = attempts
            limit = (1 if key[1] == 'email' else 5) if action == 'send' else 10
            if len(attempts) >= limit:
                retry = max(1, math.ceil(60 - (clock - attempts[0])))
                detail = (f'Wait {retry} seconds before requesting another code' if action == 'send'
                          else f'Too many authentication attempts. Try again in {retry} seconds')
                raise HTTPException(429, detail, headers={'Retry-After': str(retry)})
        for key in keys:
            _attempts[key].append(clock)
            _attempts.move_to_end(key)
        while len(_attempts) > 2048:
            _attempts.popitem(last=False)


class EmailBody(BaseModel):
    email: str = Field(min_length=3, max_length=255)

    @field_validator('email')
    @classmethod
    def email_address(cls, value):
        value = value.strip().casefold()
        if value.count('@') != 1 or not all(value.split('@')) or any(c.isspace() for c in value):
            raise ValueError('Enter a valid email address')
        return value


class OtpRequest(EmailBody):
    signup: bool = False


class OtpVerify(EmailBody):
    code: str = Field(pattern=r'^[0-9]{6,10}$')
    name: str = Field(default='', max_length=100)

    @field_validator('name')
    @classmethod
    def clean_name(cls, value):
        return value.strip()


def make_router(get_db, csrf_dependency):
    router = APIRouter(prefix='/api/auth', tags=['authentication'])

    @router.get('/config')
    def config(request: Request):
        mode = provider()
        configured = True
        if mode == 'supabase':
            try:
                settings()
            except HTTPException:
                configured = False
        return {'provider': mode, 'configured': configured, 'method': 'email_otp' if mode == 'supabase' else 'password',
                'has_session': bool(request.cookies.get(ACCESS_COOKIE) or request.cookies.get(REFRESH_COOKIE))}

    @router.post('/otp', dependencies=[Depends(csrf_dependency), Depends(require_supabase)])
    def send_code(body: OtpRequest, request: Request, db: Session = Depends(get_db)):
        # Bound account-existence checks too, without consuming an email cooldown
        # for a rejected duplicate signup. The user can immediately choose sign-in.
        limit_attempts(request, body.email, 'request')
        if body.signup and db.scalar(select(User.id).where(func.lower(User.email) == body.email)):
            raise HTTPException(409, 'An account with this email already exists. Sign in instead')
        limit_attempts(request, body.email, 'send')
        # Name is local-only. No loan information or profile metadata goes to Supabase.
        auth_request('POST', '/otp', {'email': body.email, 'create_user': body.signup})
        return {'ok': True, 'message': 'If eligible, a sign-in code has been sent. Check your inbox', 'retry_after_seconds': 60}

    @router.post('/verify', dependencies=[Depends(csrf_dependency), Depends(require_supabase)])
    def verify_code(body: OtpVerify, request: Request, response: Response, db: Session = Depends(get_db)):
        limit_attempts(request, body.email, 'verify')
        session = auth_request('POST', '/verify', {'email': body.email, 'token': body.code, 'type': 'email'})
        access = session.get('access_token')
        if not isinstance(access, str) or not access:
            raise HTTPException(503, 'Invalid authentication session response')
        subject, email = verified_identity(access)
        if email != body.email:
            raise HTTPException(401, 'Verified account does not match the requested email')
        set_session(response, session)
        user = provision_user(db, subject, email, body.name)
        return {'id': user.id, 'name': user.name, 'email': user.email}

    @router.post('/refresh', dependencies=[Depends(csrf_dependency), Depends(require_supabase)])
    def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
        token = request.cookies.get(REFRESH_COOKIE)
        if not token:
            raise HTTPException(401, 'Please sign in again')
        session = auth_request('POST', '/token?grant_type=refresh_token', {'refresh_token': token})
        access = session.get('access_token')
        if not isinstance(access, str) or not access:
            raise HTTPException(503, 'Invalid authentication session response')
        subject, _ = verified_identity(access)
        if not find_user(db, subject):
            raise HTTPException(401, 'Local account not found; sign in again')
        set_session(response, session)
        return {'ok': True}

    @router.post('/logout', dependencies=[Depends(csrf_dependency), Depends(require_supabase)])
    def logout(request: Request, response: Response):
        token = request.cookies.get(ACCESS_COOKIE)
        refresh_token = request.cookies.get(REFRESH_COOKIE)
        revoked = False
        try:
            if token:
                try:
                    auth_request('POST', '/logout?scope=local', token=token)
                    revoked = True
                except HTTPException as error:
                    # A stale access cookie must not prevent revocation through
                    # a still-valid refresh token. Do not retry provider outages.
                    if error.status_code != 401:
                        raise
            if not revoked and refresh_token:
                refreshed = auth_request('POST', '/token?grant_type=refresh_token', {'refresh_token': refresh_token})
                token = refreshed.get('access_token')
                if isinstance(token, str) and token:
                    auth_request('POST', '/logout?scope=local', token=token)
                    revoked = True
        except HTTPException:
            pass  # Always allow browser sign-out, including during an outage.
        clear_session(response)
        return {'ok': True, 'provider_session_revoked': revoked}

    return router
