# Vercel public testing deployment

Current public deployment: https://udhaar-mvp.vercel.app, project `udhaar-mvp`.

The project deploys as a native FastAPI Python function. Supabase continues to
provide PostgreSQL and Auth, and Resend sends invitations and acknowledgment
emails. Docker remains the local development setup.

Vercel's free Hobby plan is restricted to personal, non-commercial use. A small
test deployment must still meet that restriction; low traffic alone does not
make a commercial project eligible.

## What the deployment files do

- `app.py` exports the existing FastAPI app for Vercel.
- `.python-version` selects Python 3.13, matching the Docker runtime.
- `requirements.txt` includes the PostgreSQL driver Vercel needs.
- `vercel.json` selects FastAPI, keeps the static files and migration metadata in
  the function bundle, includes the repository privacy/terms/license documents,
  and sets a 60-second request limit.
- `.vercelignore` allows only runtime source files to be uploaded. Local `.env`,
  databases, backups, test files, and other workspace files stay off Vercel.
- The Vercel build checks the database revision and model compatibility. It never
  applies migrations as a side effect of a build or HTTP request.
- On Vercel, SQLAlchemy uses `NullPool` and psycopg prepared statements are
  disabled. Supabase's transaction pooler owns connection pooling across function
  instances. Docker retains its existing connection settings.

## 1. Sign in and link the project

From the repository root:

```powershell
vercel login
vercel link
```

Choose your personal Hobby account, create a project (for example `udhaar-mvp`),
and use the current directory as its root. The framework preset is **FastAPI**.
Vercel does not run `compose.supabase.yaml` or the Dockerfile for this deployment.

## 2. Configure Production environment variables

In **Vercel Project → Settings → Environment Variables**, add these for
**Production**. Keep database credentials and the Resend key sensitive.
Values are configured separately from your local `.env`.

| Variable | Value |
| --- | --- |
| `UDHAAR_ENV` | `production` |
| `UDHAAR_AUTH_PROVIDER` | `supabase` |
| `UDHAAR_DATABASE_SCHEMA` | `udhaar` |
| `UDHAAR_DATABASE_URL` | Supabase **Transaction pooler** URI, port `6543`, with `sslmode=require` |
| `UDHAAR_COOKIE_SECURE` | `true` |
| `SUPABASE_URL` | Same project URL as your local setup |
| `SUPABASE_PUBLISHABLE_KEY` | Same publishable key as your local setup |
| `RESEND_API_KEY` | Your sending API key |
| `UDHAAR_EMAIL_FROM` | Your verified sender |
| `UDHAAR_PUBLIC_URL` | Actual stable `https://...vercel.app` project domain, without a path |

Copy the Transaction pooler URI from **Supabase → Connect**. URL-encode special
characters in the database password. Vercel reads `UDHAAR_DATABASE_URL` directly;
the Docker-only variable `SUPABASE_DATABASE_URL` is not used by the Vercel app.
The Vercel platform supplies `VERCEL=1` to select serverless connection handling.

Alternatively, after linking the correct project, copy the existing working
Compose settings without displaying credentials:

```powershell
.\.venv\Scripts\python.exe scripts/configure_vercel.py --public-url https://your-project.vercel.app
```

The helper changes the Supabase pooler port to `6543` for Vercel only, enables
secure cookies, and stores the database URL and Resend key as sensitive variables.
It does not modify local `.env` and only configures the Production target.

Use your actual assigned project domain from **Vercel → Settings → Domains**,
not an assumed available hostname or a deployment-specific random hostname.
Changing Vercel environment variables requires a new deployment to take effect.
Leave the local `.env` URL at `http://localhost:8001` for local testing.

Configure these secrets for Preview only if you intentionally want additional
preview deployments to access this same database and send real email. Preview
deployments and Production deployments are separate targets; **Production** here
selects a stable public Vercel URL for the test app.

## 3. Check migrations and deploy

The current database was migrated by the Docker release step. If future changes
introduce a migration, apply it through the existing session-pooler deployment
path before deploying compatible app code:

```powershell
docker compose -f compose.supabase.yaml run --rm --build migrate
vercel --prod
```

If no migration changed, just run `vercel --prod`. Vercel runs the read-only
`python -m backend.migrate check` command during the build and fails clearly if
the database needs an upgrade. All routes share the same HTTPS origin, including
`/api`, `/signup`, `/share/...`, and `/static`.

For deployment from Git, push the deployment files and import the repository in
Vercel using the same root, framework, and environment variables. The CLI route
does not require publishing or pushing the repository.

## 4. Verify public access

1. Open the project domain, `/api/health`, `/privacy`, `/terms`, and `/rights` in a fresh browser.
2. Sign in using an email code, reload, and confirm the session is retained.
3. Send an app invitation and open it on another device.
4. Send one acknowledgment to an existing user and one to a guest. Verify inbox
   acceptance, anonymous link acceptance, and return acknowledgment.
5. Check that email links use the stable HTTPS project domain.

The stable public domain must be accessible without a Vercel login for guests to
use emailed acknowledgment links. The app still requires its own authentication
for private records and inboxes.

The app's OTP cooldown is process-local, so it is not a global cross-instance
limiter on Vercel. Supabase Auth's provider rate limits remain authoritative.
Regular invitations have a database-enforced daily limit across all instances.

References: [FastAPI on Vercel](https://vercel.com/docs/frameworks/backend/fastapi),
[Python runtime](https://vercel.com/docs/functions/runtimes/python),
[Hobby plan](https://vercel.com/docs/plans/hobby),
[Supabase connections](https://supabase.com/docs/guides/database/connecting-to-postgres),
[prepared statements](https://supabase.com/docs/guides/troubleshooting/disabling-prepared-statements-qL8lEL).
