# Database connections, queries, and migrations

## Choose the correct environment

| Runtime | Database | Schema | Connection mode |
| --- | --- | --- | --- |
| Public Vercel app | Hosted Supabase | `udhaar` | Transaction pooler, port 6543; `NullPool`; prepared statements disabled |
| `compose.supabase.yaml` | Hosted Supabase | `udhaar` | Session pooler, port 5432; up to 3 + 2 overflow connections per process |
| `compose.yaml` | Local Docker PostgreSQL | `public` | Host `db` inside Compose; localhost externally |
| Direct Python defaults | Local SQLite file | None | Development only |

Vercel and hosted-data Docker currently use the same hosted database and Auth
project. Local Docker PostgreSQL is separate; no automatic data copy happens
between databases. The Supabase Data API, Storage, and Realtime are not required.

Copy the actual pooler URI from **Supabase → Connect**. Use the database password,
URL-encode its special characters, and retain `sslmode=require` or stronger
certificate verification. Dashboard credentials, database passwords, and API keys
are different credentials.

- Local hosted-data Compose reads `SUPABASE_DATABASE_URL` from `.env` and passes
  it to the backend as `UDHAAR_DATABASE_URL`.
- Vercel reads `UDHAAR_DATABASE_URL` directly from its Production environment.
  `VERCEL=1` enables serverless pooling behavior; the deploy helper changes the
  shared pooler port for the Vercel copy only.
- Hosted environments require PostgreSQL, a private schema, and TLS. Production
  also requires Supabase Auth and secure cookies; it cannot fall back to SQLite.

## Inspect data in Supabase

Open **Table Editor** and select schema **udhaar**. For queries, use **SQL Editor**
and fully qualify app tables:

```sql
SELECT version_num FROM udhaar.alembic_version;
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'udhaar' ORDER BY table_name;
SELECT id, kind, direction, mode, acknowledgment, created_at
FROM udhaar.records ORDER BY created_at DESC LIMIT 100;
SELECT recipient_email, delivery, state, expires_at
FROM udhaar.invitations ORDER BY created_at DESC LIMIT 100;
```

There are ten app tables plus `alembic_version`; see the
[schema diagram](understanding-the-setup.md#tables). Supabase Auth sessions are
in `auth.sessions`, not the local-mode `udhaar.login_sessions` table.
Dashboard SQL normally has elevated access; a successful admin query does not
establish what an app user is allowed to see.

Use database reports for resource/connection usage, query performance views for
slow statements, Postgres logs for DB errors, and Auth logs for sign-in errors.
Local pgAdmin is at http://localhost:5050 with the configured pgAdmin login;
the registered `db` server then needs `POSTGRES_PASSWORD` separately.

## Apply schema changes explicitly

| Revision | Change |
| --- | --- |
| `0001_initial` | Frozen original nine-table schema |
| `0002_private_access` | Schema/table role restrictions and RLS |
| `0003_email_invitations` | Regular invitation slots and loan recipient/delivery fields |

Startup only checks revision and required tables. Releases apply migrations;
Vercel builds additionally compare columns, indexes, and constraints to the model.
Commands run in an explicitly configured backend environment:

```powershell
python -m backend.migrate current
python -m backend.migrate upgrade
python -m backend.migrate check
```

For the hosted database, use the existing session-pooler release container:

```powershell
docker compose -f compose.supabase.yaml run --rm --build migrate
docker compose -f compose.supabase.yaml exec -T app python -m backend.migrate check
```

For a legacy unversioned database, back it up, run `baseline`, then `upgrade`.
Baseline accepts only the complete original frozen schema; it refuses partial
or drifted databases. It does not rewrite data. PostgreSQL migration commands use
a schema-specific transaction advisory lock to serialize simultaneous upgrades.
Security/email revisions intentionally do not provide automatic destructive
downgrades. Plan compatible forward changes and tested restores.

## Access and operations

ORM references are explicitly schema-qualified. Hosted migrations revoke direct
schema/table access from `PUBLIC`, `anon`, `authenticated`, and `service_role`
where present, and enable RLS without browser-access policies. Do not expose
`udhaar` in the Supabase Data API or grant those roles access.

The backend connects as table owner, which bypasses RLS. FastAPI must still check
ownership, recipient identity, and lender rules. A separately scoped runtime role
is a future hardening step; current RLS is not a replacement for API authorization.

Stopping Docker does not remove Supabase data. Local PostgreSQL volumes survive
`docker compose down`; `down -v` deletes the local volumes. A 30-day link expiry
does not purge invitation or loan rows. Follow [Operations](operations.md) for
backups, restore checks, and verified data requests.

Tests support SQLite and isolated PostgreSQL schemas, including upgrade
preservation, drift/baseline refusal, unrelated schema isolation, RLS boundaries,
and transaction-pooler connection options. Set `TEST_DATABASE_URL` only to a
database where the test account may create/drop temporary schemas.

References: [Supabase connections](https://supabase.com/docs/guides/database/connecting-to-postgres),
[prepared statements](https://supabase.com/docs/guides/troubleshooting/disabling-prepared-statements-qL8lEL),
[API security](https://supabase.com/docs/guides/api/securing-your-api).
