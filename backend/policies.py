"""Public policy pages rendered from the same documents shipped in the repository."""
from html import escape
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse
from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parent.parent
OWNER = 'Gopi krishna Gajam'
PROFILE = 'https://github.com/gopikrishnagajam'
PAGES = {'privacy': ('PRIVACY.md', 'Privacy'), 'terms': ('TERMS.md', 'Terms'), 'rights': ('RIGHTS.md', 'Rights & license')}
DOCUMENT_LINKS = {'PRIVACY.md': '/privacy', 'TERMS.md': '/terms', 'RIGHTS.md': '/rights', 'LICENSE': '/license'}
router = APIRouter(include_in_schema=False)


def policy_page(name):
    filename, title = PAGES[name]
    renderer = MarkdownIt('commonmark', {'html': False})
    tokens = renderer.parse((ROOT / filename).read_text(encoding='utf-8'))
    for token in tokens:
        for child in token.children or []:
            if child.type == 'link_open' and child.attrGet('href') in DOCUMENT_LINKS:
                child.attrSet('href', DOCUMENT_LINKS[child.attrGet('href')])
    content = renderer.renderer.render(tokens, renderer.options, {})
    links = ''.join(f'<a href="/{slug}"'+(' aria-current="page"' if slug == name else '')+f'>{escape(label)}</a>'
                    for slug, (_, label) in PAGES.items())
    html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Udhaar {escape(title)}"><title>{escape(title)} | Udhaar</title>
<link rel="icon" type="image/png" href="/static/branding/logo.png">
<link rel="apple-touch-icon" href="/static/branding/logo.png">
<link rel="stylesheet" href="/static/style.css"></head><body class="policy-body">
<a class="skip-link" href="#policy-content">Skip to content</a>
<header class="policy-header"><a class="brand" href="/" aria-label="Udhaar home"><span class="brand-mark"><img src="/static/branding/logo.png" alt="" width="36" height="36"></span>udhaar<span class="brand-dot">.</span></a>
<nav aria-label="Policy navigation">{links}<a href="/">Back to app</a></nav></header>
<main class="policy-content" id="policy-content">{content}</main>
<footer class="site-footer"><span>&copy; 2026 <a href="{PROFILE}">{escape(OWNER)}</a></span>
<span>Udhaar &middot; <a href="/license">MIT License</a></span></footer></body></html>'''
    return HTMLResponse(html)


@router.get('/privacy')
def privacy():
    return policy_page('privacy')


@router.get('/terms')
def terms():
    return policy_page('terms')


@router.get('/rights')
def rights():
    return policy_page('rights')


@router.get('/license')
def license_text():
    return FileResponse(ROOT / 'LICENSE', media_type='text/plain')
