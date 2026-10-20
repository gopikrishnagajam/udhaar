"""Public notices stay available without signing in and use canonical repo text."""
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize('path, heading', [
    ('/privacy', 'Privacy notice'),
    ('/terms', 'Terms of use'),
    ('/rights', 'Rights and licensing'),
])
def test_policy_pages_are_public_and_link_back_to_app(setup, path, heading):
    _, guest, _ = setup
    response = guest.get(path)
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/html')
    assert f'<h1>{heading}</h1>' in response.text
    assert 'Gopi krishna Gajam' in response.text
    assert 'https://github.com/gopikrishnagajam' in response.text
    assert 'href="/"' in response.text
    assert 'href="/privacy"' in response.text
    assert 'href="/terms"' in response.text
    assert 'href="/rights"' in response.text
    assert 'href="PRIVACY.md"' not in response.text
    assert 'href="TERMS.md"' not in response.text
    assert 'href="RIGHTS.md"' not in response.text
    assert response.headers['cache-control'] == 'no-store'
    assert guest.get('/api/me').status_code == 401


def test_full_mit_license_and_global_footer_are_public(setup):
    _, guest, _ = setup
    license_response = guest.get('/license')
    assert license_response.status_code == 200
    assert license_response.headers['content-type'].startswith('text/plain')
    assert license_response.content == (ROOT / 'LICENSE').read_bytes()
    assert 'Permission is hereby granted, free of charge' in license_response.text
    for path in ('/', '/signup', '/share/unavailable-test-link'):
        response = guest.get(path)
        assert response.status_code == 200
        for link in ('/privacy', '/terms', '/rights'):
            assert f'href="{link}"' in response.text
        assert 'Gopi krishna Gajam' in response.text


def test_privacy_notice_describes_current_manual_controls_and_bearer_links(setup):
    _, guest, _ = setup
    response = guest.get('/privacy')
    text = ' '.join(response.text.split())
    for disclosure in ('manual assistance', 'no automatic age-based purge', 'not end-to-end encrypted',
                       'udhaar_sb_access', 'udhaar_sb_refresh', 'udhaar_csrf', 'udhaar_session'):
        assert disclosure in text
    assert 'Do not post your email address' in response.text
    assert 'href="/license"' in guest.get('/rights').text
