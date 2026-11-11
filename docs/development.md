# Development and testing

Use Python 3.13, matching the Docker runtime and Vercel configuration. Docker
Desktop must use Linux containers. The frontend is plain HTML, JavaScript,
and CSS with no build step.

## Choose an environment

| Environment | Runtime | Application database | Authentication |
| --- | --- | --- | --- |
| Public beta | Vercel HTTPS | Supabase, private `udhaar` schema | Supabase |
| Hosted-data development | Docker, localhost:8001 | Configured Supabase database | Supabase |
| Isolated Docker | Docker, localhost:8000 | Local PostgreSQL, `public` schema | Supabase by default; optional local mode |
| Direct Python defaults | localhost:8000 | Local SQLite file | Local password mode |

Hosted-data development can point at the same database and Auth project as the
public app. Writes there affect shared data. Prefer isolated development for
routine work. Cookies span ports on a hostname; use separate browser profiles
when testing multiple local deployments.

## Direct Python setup

With no hosted environment variables set:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m backend.migrate upgrade
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Open http://localhost:8000. On macOS/Linux use `.venv/bin/python`.
Python does not automatically load `.env`. Private records need no external
credentials; email flows require a verified sender and reachable public origin.

## Isolated Docker PostgreSQL

Copy `.env.example` to `.env` only on first setup; preserve an existing file.
Set `POSTGRES_PASSWORD` and `PGADMIN_PASSWORD`. For local password authentication,
set `UDHAAR_AUTH_PROVIDER=local` in that file.

```powershell
docker compose -f compose.yaml up --build -d
docker compose -f compose.yaml ps
```

The app is at http://localhost:8000 and pgAdmin at http://localhost:5050.
Compose applies migrations before starting the app. The database volume persists
when containers stop; deleting volumes deletes the local database.

## Hosted-data Docker

Configure Supabase credentials using [Authentication](authentication.md) and
[Database](database.md), plus [Email delivery](email-invitations.md).

```powershell
docker compose -f compose.supabase.yaml up --build -d
docker compose -f compose.supabase.yaml ps
docker compose -f compose.supabase.yaml logs --tail 50 app migrate
```

Open http://localhost:8001. This stack is a staging configuration using the
configured hosted data. It is not a production VPS deployment template.

## Automated checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests
docker compose -f compose.yaml --profile test run --build --rm tests
npm ci --prefix tests/browser
npm run test:invitations --prefix tests/browser
npm run test:mobile --prefix tests/browser
```

API tests use temporary SQLite databases or isolated PostgreSQL schemas when
`TEST_DATABASE_URL` is provided. That test account must be permitted to create
and drop temporary schemas. Provider Auth and email delivery are simulated.

Invitation and mobile browser tests start disposable servers. Session browser
checks use an already running Supabase-mode app:

```powershell
$env:UDHAAR_TEST_BASE_URL='http://localhost:8001'
npm test --prefix tests/browser
```

Use a modern Node.js runtime and installed Microsoft Edge, or set
`UDHAAR_TEST_BROWSER_CHANNEL` / `UDHAAR_TEST_BROWSER_PATH`.
A local-password smoke test is available as
`python scripts/smoke_test.py http://localhost:8000`; it creates test accounts
and records, so run it only against disposable local data.

Real email delivery and authenticated public journeys require separate checks.
The API reference is at `/api/docs`; the OpenAPI schema is at `/api/openapi.json`.

## Repository layout

| Path | Responsibility |
| --- | --- |
| `backend/` | API, authorization, record rules, models, auth, email, policy rendering |
| `static/` | Browser interface and runtime branding assets |
| `migrations/` | Versioned Alembic upgrades; preserve historical revisions |
| `tests/` | API/database regressions and browser scenarios |
| `scripts/` | Vercel configuration helper and local smoke test |
| `docker/` | Local pgAdmin configuration |
| `docs/` | Product direction, technical guides, roadmap, and legal research |
| Root deployment files | Docker, Compose, Vercel, dependencies, and runtime entrypoint |
| Root policy files | Canonical public privacy, terms, licensing, and security notices |

## Change workflow

Read the workspace's `TODO.md` before proposing or implementing changes.
Work through estimated complexity unless the user directs otherwise, and record
the reason for reordering. Keep IDs, summary status, evidence, and acceptance
checks consistent. Local validation means Ready for prod retest; Done requires
public acceptance.

Keep current guides aligned with code. Label planned features explicitly.
`TODO.md` and `AGENTS.md` are currently ignored local workflow files; preserve
them and keep shared product decisions in the tracked documentation.
Never commit `.env`, credentials, local databases, private logs, or backups.
