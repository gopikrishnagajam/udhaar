"""Copy the working Compose settings to the linked Vercel Production target.

Values travel through subprocess stdin and are never printed or put in shell
arguments. Local .env is unchanged. Run after `vercel link`:
    python scripts/configure_vercel.py --public-url https://your-project.vercel.app
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-url', required=True)
    args = parser.parse_args()
    origin = args.public_url.rstrip('/')
    parsed = urlsplit(origin)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment):
        parser.error('Use the stable HTTPS project origin without a path')
    cli = shutil.which('vercel.cmd') or shutil.which('vercel')
    if not cli or not (ROOT / '.vercel' / 'project.json').exists():
        parser.error('Install the Vercel CLI, then run vercel login and vercel link')
    compose = subprocess.run(['docker', 'compose', '-f', 'compose.supabase.yaml', 'config', '--format', 'json'],
        cwd=ROOT, capture_output=True, text=True)
    if compose.returncode:
        parser.error('Could not resolve Compose settings; run docker compose config --quiet to check .env')
    source = json.loads(compose.stdout)['services']['app']['environment']
    required = ('UDHAAR_DATABASE_URL', 'SUPABASE_URL', 'SUPABASE_PUBLISHABLE_KEY', 'RESEND_API_KEY', 'UDHAAR_EMAIL_FROM')
    for name in required:
        if not source.get(name):
            parser.error(f'Missing {name} in the Compose app environment')
    url = make_url(source['UDHAAR_DATABASE_URL'])
    if not url.host or not url.host.endswith('.pooler.supabase.com') or url.port not in {5432, 6543}:
        parser.error('Use a Supabase pooler URL in SUPABASE_DATABASE_URL; keep the session pooler on port 5432 locally')
    url = url.set(drivername='postgresql+psycopg', port=6543)
    if url.query.get('sslmode') not in {'require', 'verify-ca', 'verify-full'}:
        parser.error('The Supabase database URL must require SSL')
    values = {name: source[name] for name in required}
    values.update(UDHAAR_DATABASE_URL=url.render_as_string(hide_password=False),
        UDHAAR_ENV='production', UDHAAR_DATABASE_SCHEMA='udhaar',
        UDHAAR_AUTH_PROVIDER='supabase', UDHAAR_COOKIE_SECURE='true', UDHAAR_PUBLIC_URL=origin)
    for name, value in values.items():
        sensitive = ['--sensitive'] if name in {'UDHAAR_DATABASE_URL', 'RESEND_API_KEY'} else []
        result = subprocess.run([cli, 'env', 'add', name, 'production', '--force', '--yes', '--non-interactive', *sensitive],
            cwd=ROOT, input=str(value), capture_output=True, text=True)
        if result.returncode:
            parser.error(f'Could not store {name} (CLI exit {result.returncode}); check vercel whoami and the linked project')
        print(f'Configured {name}')
    print('Production settings configured. No credentials were printed; local .env is unchanged.')


if __name__ == '__main__':
    main()
