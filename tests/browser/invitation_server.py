"""Disposable browser-test app. Never points at a real database or sends mail."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def run():
    with tempfile.TemporaryDirectory(prefix='udhaar-invitation-browser-') as folder:
        port = int(os.getenv('UDHAAR_TEST_PORT', '8012'))
        os.environ.update(UDHAAR_DATABASE_URL=f'sqlite:///{Path(folder) / "test.sqlite3"}',
            UDHAAR_ENV='development', UDHAAR_DATABASE_SCHEMA='public', UDHAAR_COOKIE_SECURE='false',
            UDHAAR_AUTH_PROVIDER=os.getenv('UDHAAR_BROWSER_AUTH_PROVIDER', 'local'),
            UDHAAR_PUBLIC_URL=f'http://127.0.0.1:{port}', RESEND_API_KEY='', UDHAAR_EMAIL_FROM='',
            SUPABASE_URL='https://browser-test.invalid', SUPABASE_PUBLISHABLE_KEY='sb_publishable_test')
        from backend import email_delivery
        from backend.migrate import upgrade_database
        from backend.main import app
        import uvicorn
        emails = []
        def fake_send(email, subject, message, key):
            emails.append({'email': email, 'subject': subject, 'message': message, 'key': key})
            return f'browser-message-{len(emails)}'
        email_delivery.send_email = fake_send
        @app.get('/__test/emails')
        def test_emails():
            return emails
        upgrade_database()
        uvicorn.run(app, host='127.0.0.1', port=port, log_level='warning')


if __name__ == '__main__':
    run()
