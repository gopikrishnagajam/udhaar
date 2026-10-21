# Udhaar

Keep track of the physical items you lend and borrow, privately or with the other
person's acknowledgment.

**Public test app:** https://udhaar-mvp.vercel.app

**Author:** [Gopi krishna Gajam](https://github.com/gopikrishnagajam)

**License:** [MIT](LICENSE)

## How it works

- **Off the Record:** private entries, editable details, and owner-recorded returns.
- **On the Record:** enter the other person's email. Existing app users receive
  an acknowledgment inbox request; others receive a private email link and can
  respond without registering. Private notes are omitted from recipient views.
- **Two acknowledgments:** accepting the handover is separate from confirming
  returned items. The lender confirms shared returns; partial returns are supported.
- **Invite friends:** two regular email invitations per account per UTC day.
  Loan acknowledgment emails are separate from that allowance.
- Shared requests expire after 30 days. Replacing one invalidates its predecessor
  and requires a new handover acknowledgment. Guest links grant access to their
  holder and do not independently verify identity.

## Deployment map

| App | Runs on | App database | Email links |
| --- | --- | --- | --- |
| Public test | Vercel, HTTPS | Supabase `udhaar` schema | `https://udhaar-mvp.vercel.app` |
| Hosted-data development | Docker, `localhost:8001` | Same Supabase project/schema when using the current `.env` | Local `.env` origin |
| Isolated local development | Docker, `localhost:8000` | Docker PostgreSQL `public` schema | Local `.env` origin |
| Optional development | Python, `localhost:8000` | SQLite | Explicitly configured origin |

The public app works with Docker and your computer turned off. The hosted-data
Docker app and Vercel currently share application data and Auth; a local write
there affects the public test data. Use the local PostgreSQL stack for isolated
development. Cookies are shared across ports on the same hostname, so use separate
browser profiles when testing multiple local deployments.

## Start the hosted-data Docker app

Use Python 3.13 for direct development, or Docker Desktop with Linux containers.
Copy `.env.example` to `.env` only on first setup; preserve an existing `.env`.
Configure Supabase Auth/database and Resend as described in the linked guides.

```powershell
docker compose -f compose.supabase.yaml up --build -d
docker compose -f compose.supabase.yaml ps
docker compose -f compose.supabase.yaml logs --tail 50 app migrate
```

Open http://localhost:8001. The one-shot migration service must exit successfully
before the app starts. `GET /api/health` checks database connectivity.

For a separate local PostgreSQL database and pgAdmin:

```powershell
docker compose -f compose.yaml up --build -d
```

This app uses port 8000 and pgAdmin uses port 5050. Set `POSTGRES_PASSWORD` and
`PGADMIN_PASSWORD` in `.env`. Both Compose apps default to Supabase Auth; set
`UDHAAR_AUTH_PROVIDER=local` only for the isolated development stack if desired.
The hosted-data stack always uses Supabase Auth.

## Run without Docker

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m backend.migrate upgrade
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

This defaults to SQLite and local password authentication when no environment
variables are set. On macOS/Linux use `.venv/bin/python`. Python does not load
`.env` automatically; Compose does. Private records work without external email
configuration. Email delivery requires a configured Resend sender and public URL.

## Update the public app

For code changes without a new database migration:

```powershell
vercel deploy --prod
```

If a migration changed, apply it first using the existing session-pooler release
path, then deploy compatible code:

```powershell
docker compose -f compose.supabase.yaml run --rm --build migrate
vercel deploy --prod
```

Vercel checks the database schema during builds. Its Production environment
variables are separate from local `.env`; public emails use the cloud
`UDHAAR_PUBLIC_URL`. See the [deployment guide](docs/vercel-deployment.md) for
setup, credentials, connection pooling, and the Hobby plan's use limits.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
docker compose -f compose.yaml --profile test run --build --rm tests
npm ci --prefix tests/browser
npm run test:invitations --prefix tests/browser
npm run test:mobile --prefix tests/browser
```

API tests use temporary SQLite databases or isolated PostgreSQL schemas when
`TEST_DATABASE_URL` is provided. Browser invitation tests start a disposable local
server. Test email delivery and provider Auth calls are simulated.
Mobile browser checks also use a disposable server and cover phone, tablet,
desktop, and landscape layouts, dialogs, navigation, and acknowledgment flows.
Session browser checks use an already running Supabase-mode app:

```powershell
$env:UDHAAR_TEST_BASE_URL='http://localhost:8001'
npm test --prefix tests/browser
```

Use a modern Node.js runtime and Microsoft Edge; browser overrides are described
in the [Auth guide](docs/supabase-implementation.md). Interactive API documentation
is available at `/api/docs` and the schema at `/api/openapi.json`.

## Documentation

| Guide | Covers |
| --- | --- |
| [Architecture and schema](docs/understanding-the-setup.md) | Components, ten app tables, permissions, and loan lifecycle |
| [Authentication](docs/supabase-implementation.md) | Email-code setup, cookies, session refresh, logout, and tests |
| [Auth rate limits](docs/auth-rate-limits.md) | Browser, process, Supabase, and sender limits |
| [Database and migrations](docs/supabase-database.md) | Connection modes, SQL inspection, schema access, and upgrades |
| [Email invitations](docs/email-invitations.md) | Resend setup, daily invite slots, guest links, and delivery |
| [Vercel deployment](docs/vercel-deployment.md) | Public hosting and cloud environment configuration |
| [Operations](docs/operations.md) | Releases, monitoring, backups, recovery, and privacy requests |

## Privacy, rights, and scope

Read the [Privacy notice](PRIVACY.md), [Terms of use](TERMS.md), and
[Rights and licensing](RIGHTS.md). The same documents are available inside the app
at `/privacy`, `/terms`, and `/rights`; the full MIT text is at `/license`.
The MIT grant applies to the source and documentation, not private user data.

This is a public testing release for item tracking. Account deletion/export need
manual assistance, the OTP cooldown is process-local, and the runtime currently
uses the database table-owner connection. Provider quotas, backups, and logs need
active operational management. There are no payments, money-loan accounting, or
automated reminders. See [Operations](docs/operations.md) for current limits.

Security reports and contact guidance are in [SECURITY.md](SECURITY.md).
Do not put personal data, credentials, or guest links in public issues.
