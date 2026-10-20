"""Invitation quotas, private recipient inboxes, and anonymous email links."""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import HTTPException

from backend import main, email_delivery
from backend.email_delivery import send_email as real_send_email
from test_mvp import account, post


def loan(client, email='recipient@example.com', mode='ON', direction='LENT', name='Recipient'):
    return post(client, '/api/records', {'direction': direction, 'mode': mode,
        'contact_name': name, 'contact_email': email, 'item_name': 'Book', 'quantity': 2,
        'loan_date': '2026-10-19', 'notes': 'Private note'})


def link(mail):
    return re.search(r'https://udhaar.example.com(/share/\S+)', mail[-1]['message']).group(1)


def test_regular_invites_are_persistent_per_user_and_reset_at_utc_midnight(setup, mail, monkeypatch):
    owner, _, stranger = setup
    account(owner, 'Owner', 'owner@example.com')
    account(stranger, 'Other', 'other@example.com')
    instant = datetime(2026, 10, 19, 23, 59, tzinfo=timezone.utc)
    monkeypatch.setattr(main, 'now', lambda: instant)
    for email in ('one@example.com', 'two@example.com'):
        assert post(owner, '/api/app-invites', {'email': email}).status_code == 200
    assert post(owner, '/api/app-invites', {'email': 'three@example.com'}).status_code == 429
    assert owner.get('/api/app-invites').json()['remaining'] == 0
    assert stranger.get('/api/app-invites').json()['remaining'] == 2
    post(owner, '/api/logout', {})
    post(owner, '/api/login', {'email': 'owner@example.com', 'password': 'StrongPass123!'})
    assert owner.get('/api/app-invites').json()['remaining'] == 0
    monkeypatch.setattr(main, 'now', lambda: instant + timedelta(minutes=2))
    assert owner.get('/api/app-invites').json()['remaining'] == 2
    assert post(owner, '/api/app-invites', {'email': 'three@example.com'}).status_code == 200
    assert len(mail) == 3
    assert '/signup' in mail[0]['message']


def test_parallel_regular_invites_cannot_send_more_than_two(setup, mail):
    owner, _, _ = setup
    account(owner, 'Owner', 'owner@example.com')
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda n: post(owner, '/api/app-invites', {'email': f'person{n}@example.com'}), range(4)))
    assert all(r.status_code in {200, 429} for r in responses), [r.text for r in responses]
    assert 1 <= sum(r.status_code == 200 for r in responses) <= 2
    assert len(mail) <= 2
    assert owner.get('/api/app-invites').json()['remaining'] == 2 - len(mail)


def test_failed_app_delivery_keeps_slot_and_retries_same_idempotency_key(setup, mail, monkeypatch):
    owner, _, stranger = setup
    account(owner, 'Owner', 'owner@example.com')
    account(stranger, 'Other', 'other@example.com')
    send = email_delivery.send_email
    attempts = []
    def fail(*args):
        attempts.append(args)
        raise HTTPException(503, 'Delivery uncertain')
    monkeypatch.setattr(email_delivery, 'send_email', fail)
    assert post(owner, '/api/app-invites', {'email': 'friend@example.com'}).status_code == 503
    quota = owner.get('/api/app-invites').json()
    assert quota['remaining'] == 1
    inv = quota['invitations'][0]
    assert inv['state'] == 'FAILED'
    assert post(stranger, f"/api/app-invites/{inv['id']}/retry", {}).status_code == 404
    monkeypatch.setattr(email_delivery, 'send_email', send)
    assert post(owner, f"/api/app-invites/{inv['id']}/retry", {}).status_code == 200
    assert mail[-1]['key'] == attempts[0][-1]
    assert owner.get('/api/app-invites').json()['remaining'] == 1
    assert post(owner, f"/api/app-invites/{inv['id']}/retry", {}).status_code == 200
    assert len(mail) == 1


@pytest.mark.parametrize('direction', ['LENT', 'BORROWED'])
def test_registered_recipient_gets_private_inbox_and_completes_returns(setup, mail, direction):
    owner, recipient, stranger = setup
    account(owner, 'Owner', 'owner@example.com')
    account(recipient, 'Recipient', 'recipient@example.com')
    account(stranger, 'Stranger', 'stranger@example.com')
    response = loan(owner, email=' RECIPIENT@EXAMPLE.COM ', direction=direction)
    assert response.status_code == 201, response.text
    rec = response.json()
    assert rec['invitation_delivery'] == 'IN_APP'
    assert len(mail) == 0
    inbox = recipient.get('/api/inbox').json()
    assert len(inbox) == 1
    item = inbox[0]
    assert 'notes' not in item and 'events' not in item and 'contact_email' not in item
    assert recipient.get('/api/records').json() == []
    assert stranger.get('/api/inbox').json() == []
    prefix = f"/api/inbox/{item['invitation_id']}"
    assert stranger.get(prefix).status_code == 404
    assert post(stranger, prefix + '/respond', {'accept': True}).status_code == 404
    assert post(recipient, prefix + '/returns', {'quantity': 1}).status_code == 409
    assert post(recipient, prefix + '/respond', {'accept': True}).status_code == 200
    assert post(recipient, prefix + '/respond', {'accept': True}).status_code == 409
    if direction == 'LENT':
        returned = post(recipient, prefix + '/returns', {'quantity': 2}).json()
        assert returned['status'] == 'PENDING'
        assert post(owner, f"/api/records/{rec['id']}/returns/{returned['id']}/confirm", {}).status_code == 200
    else:
        returned = post(owner, f"/api/records/{rec['id']}/returns", {'quantity': 2}).json()
        assert post(recipient, prefix + f"/returns/{returned['id']}/confirm", {}).status_code == 200
    assert recipient.get(prefix).json()['settlement'] == 'RETURNED'
    assert owner.get('/api/app-invites').json()['remaining'] == 2


def test_guest_email_acknowledgments_are_uncapped_and_signup_is_optional(setup, mail):
    owner, guest, _ = setup
    account(owner, 'Owner', 'owner@example.com')
    for n in range(2):
        assert post(owner, '/api/app-invites', {'email': f'friend{n}@example.com'}).status_code == 200
    for n in range(4):
        response = loan(owner, email=f'guest{n}@example.com')
        assert response.status_code == 201
        assert response.json()['invitation_delivery'] == 'EMAIL'
    assert owner.get('/api/app-invites').json()['remaining'] == 0
    assert len(mail) == 6
    assert '/signup' in mail[-1]['message'] and 'No account is needed' in mail[-1]['message']
    prefix = '/api' + link(mail)
    assert guest.get('/api/me').status_code == 401
    assert post(guest, prefix + '/respond', {'accept': True}).status_code == 200
    returned = post(guest, prefix + '/returns', {'quantity': 2}).json()
    record_id = response.json()['id']
    assert post(owner, f"/api/records/{record_id}/returns/{returned['id']}/confirm", {}).status_code == 200
    assert guest.get(prefix).json()['settlement'] == 'RETURNED'


def test_conversion_replacement_decline_and_expiration(setup, mail, monkeypatch):
    owner, recipient, _ = setup
    account(owner, 'Owner', 'owner@example.com')
    account(recipient, 'Recipient', 'recipient@example.com')
    rec = loan(owner, mode='OFF').json()
    assert mail == []
    share = f"/api/records/{rec['id']}/share"
    assert post(owner, share, {'email': 'guest@example.com'}).status_code == 200
    guest_path = '/api' + link(mail)
    assert post(owner, share, {'email': 'recipient@example.com'}).json()['delivery'] == 'IN_APP'
    assert recipient.get(guest_path).status_code == 404
    item = recipient.get('/api/inbox').json()[0]
    prefix = f"/api/inbox/{item['invitation_id']}"
    assert post(recipient, prefix + '/respond', {'accept': False}).status_code == 200
    assert recipient.get('/api/inbox').json() == []
    assert owner.get(f"/api/records/{rec['id']}").json()['acknowledgment'] == 'DECLINED'
    assert post(owner, share, {'email': 'recipient@example.com'}).status_code == 200
    fresh = recipient.get('/api/inbox').json()[0]
    instant = main.now()
    monkeypatch.setattr(main, 'now', lambda: instant + timedelta(days=31))
    # Refresh the local test session after advancing beyond its own lifetime.
    assert post(recipient, '/api/login', {'email': 'recipient@example.com', 'password': 'StrongPass123!'}).status_code == 200
    assert recipient.get('/api/inbox').json() == []
    assert post(recipient, f"/api/inbox/{fresh['invitation_id']}/respond", {'accept': True}).status_code == 404


def test_loan_email_failure_rolls_back_and_preserves_previous_link(setup, mail, monkeypatch):
    owner, guest, _ = setup
    account(owner, 'Owner', 'owner@example.com')
    rec = loan(owner).json()
    old_path = '/api' + link(mail)
    def fail(*args):
        raise HTTPException(503, 'Email unavailable')
    monkeypatch.setattr(email_delivery, 'send_email', fail)
    assert post(owner, f"/api/records/{rec['id']}/share", {'email': 'other@example.com'}).status_code == 503
    assert guest.get(old_path).status_code == 200
    assert loan(owner, email='different@example.com').status_code == 503
    assert len(owner.get('/api/records').json()) == 1


@pytest.mark.parametrize('email', ['invalid', 'a@@example.com', 'a@example', 'a b@example.com', 'Name <a@example.com>', 'a@example.com\nBcc: x@y.com'])
def test_email_validation_on_all_invitation_paths(setup, email):
    owner, _, _ = setup
    account(owner, 'Owner', 'owner@example.com')
    rec = loan(owner, mode='OFF').json()
    assert post(owner, '/api/app-invites', {'email': email}).status_code == 422
    assert post(owner, f"/api/records/{rec['id']}/share", {'email': email}).status_code == 422
    assert loan(owner, email=email).status_code == 422


def test_missing_email_self_invites_csrf_and_contact_identity(setup):
    owner, guest, _ = setup
    account(owner, 'Owner', 'owner@example.com')
    assert loan(owner, email=None).status_code == 422
    assert loan(owner, email='owner@example.com').status_code == 422
    assert post(owner, '/api/app-invites', {'email': 'owner@example.com'}).status_code == 422
    assert guest.get('/api/inbox').status_code == 401
    assert guest.get('/api/app-invites').status_code == 401
    assert owner.post('/api/app-invites', json={'email': 'friend@example.com'}).status_code == 403
    a = loan(owner, email='person1@example.com', mode='OFF').json()
    b = loan(owner, email='person2@example.com', mode='OFF').json()
    assert a['contact_email'] != b['contact_email']


def test_resend_boundary_and_safe_errors(monkeypatch):
    monkeypatch.setenv('RESEND_API_KEY', 'test-secret')
    monkeypatch.setenv('UDHAAR_EMAIL_FROM', 'Udhaar <invites@example.com>')
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'id': 'message-123'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(email_delivery.httpx, 'post', client.post)
        assert real_send_email('person@example.com', 'Subject', 'Message', 'test/key') == 'message-123'
    assert requests[0].headers['authorization'] == 'Bearer test-secret'
    assert requests[0].headers['idempotency-key'] == 'test/key'
    monkeypatch.setattr(email_delivery.httpx, 'post', lambda *a, **k: httpx.Response(403, json={'message': 'test-secret'}))
    with pytest.raises(HTTPException) as error:
        real_send_email('person@example.com', 'Subject', 'Message', 'test/key')
    assert error.value.status_code == 503
    assert 'test-secret' not in error.value.detail


@pytest.mark.parametrize('origin', ['', 'https://example.com/path', 'http://evil.example', 'https://user:pass@example.com', 'https://example.com?next=x'])
def test_email_links_require_configured_trusted_origin(monkeypatch, origin):
    monkeypatch.setenv('UDHAAR_PUBLIC_URL', origin)
    with pytest.raises(HTTPException):
        email_delivery.public_url('/signup')
