"""Exercise a running app. Creates one test account and completed loan per run.

Run: python scripts/smoke_test.py [http://localhost:8000]
"""
import json
import secrets
import sys
from datetime import date
from http.cookiejar import CookieJar
from urllib.request import HTTPCookieProcessor, Request, build_opener


class Client:
    def __init__(self, base):
        self.base = base.rstrip('/')
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self.csrf = self.call('/api/csrf')['csrf']

    def call(self, path, body=None):
        headers = {}
        if body is not None:
            headers = {'Content-Type': 'application/json', 'X-CSRF-Token': self.csrf}
        request = Request(self.base + path, headers=headers,
                          data=json.dumps(body).encode() if body is not None else None)
        with self.opener.open(request, timeout=15) as response:
            return json.load(response)


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else 'http://localhost:8000'
    owner, guest = Client(base), Client(base)
    assert owner.call('/api/health')['ok']
    email = f'smoke-{secrets.token_hex(8)}@example.com'
    password = secrets.token_urlsafe(24)
    owner.call('/api/register', {'name': 'Docker smoke test', 'email': email, 'password': password})
    record = owner.call('/api/records', {
        'direction': 'LENT', 'mode': 'ON', 'contact_name': 'Link holder',
        'item_name': 'Docker test book', 'quantity': 2, 'loan_date': date.today().isoformat(),
        'notes': 'This note must remain private',
    })
    path = owner.call(f"/api/records/{record['id']}/share", {})['path']
    assert 'notes' not in guest.call('/api' + path)
    guest.call('/api' + path + '/respond', {'accept': True})
    proposed = guest.call('/api' + path + '/returns', {'quantity': 2})
    assert proposed['status'] == 'PENDING'
    owner.call(f"/api/records/{record['id']}/returns/{proposed['id']}/confirm", {})
    result = guest.call('/api' + path)
    assert result['handover_acknowledgment'] == 'CONFIRMED'
    assert result['return_acknowledgment'] == 'CONFIRMED'
    assert result['settlement'] == 'RETURNED'
    owner.call('/api/logout', {})
    owner.call('/api/login', {'email': email, 'password': password})
    assert owner.call('/api/me')['email'] == email
    assert owner.call(f"/api/records/{record['id']}")['settlement'] == 'RETURNED'
    print('PASS: health, signup, private notes, anonymous handover, return acknowledgment, logout and login')
    print('Completed test record:', record['id'])


if __name__ == '__main__':
    main()
