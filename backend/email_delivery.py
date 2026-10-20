"""Transactional invitations through Resend; Supabase still owns authentication."""
import os
from urllib.parse import urlsplit

import httpx
from email_validator import EmailNotValidError, validate_email
from fastapi import HTTPException


def normalize_email(value):
    try:
        return validate_email(value.strip(), check_deliverability=False).normalized.casefold()
    except (EmailNotValidError, AttributeError):
        raise ValueError('Enter a valid email address') from None


def public_url(path):
    base = os.getenv('UDHAAR_PUBLIC_URL', '').strip().rstrip('/')
    parsed = urlsplit(base)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment or parsed.path
            or (parsed.scheme == 'http' and parsed.hostname not in {'localhost', '127.0.0.1'})):
        raise HTTPException(503, 'Email links are not configured. Set UDHAAR_PUBLIC_URL to the public HTTPS app origin')
    return base + path


def send_email(email, subject, message, key):
    key_value = os.getenv('RESEND_API_KEY', '').strip()
    sender = os.getenv('UDHAAR_EMAIL_FROM', '').strip()
    if not key_value or not sender:
        raise HTTPException(503, 'Invitation email is not configured. Set RESEND_API_KEY and UDHAAR_EMAIL_FROM')
    try:
        result = httpx.post('https://api.resend.com/emails',
            headers={'Authorization': f'Bearer {key_value}', 'Idempotency-Key': key},
            json={'from': sender, 'to': [email], 'subject': subject, 'text': message}, timeout=15)
    except httpx.HTTPError:
        raise HTTPException(503, 'Email delivery could not be confirmed. Please retry') from None
    if not 200 <= result.status_code < 300:
        raise HTTPException(503, 'Email delivery failed. Please retry; the administrator can check Resend logs')
    try:
        message_id = result.json()['id']
        if not isinstance(message_id, str) or not message_id:
            raise ValueError()
        return message_id
    except (ValueError, KeyError, TypeError):
        raise HTTPException(503, 'Email delivery could not be confirmed. Please retry') from None
