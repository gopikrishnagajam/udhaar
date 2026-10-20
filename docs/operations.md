# Operating the public test app

## Environments and release

The public app is https://udhaar-mvp.vercel.app. Vercel runs the frontend/backend;
Supabase provides Auth/database and Resend sends email. Closing Docker does not
stop the public app. Hosted-data Docker and Vercel currently share the Supabase
database and accounts. Use local Docker PostgreSQL for isolated development.

For a code-only release, run relevant tests and `vercel deploy --prod`. The build
performs a read-only schema check. If migrations changed, back up first and apply
them with the session-pooler migration container before deploying compatible
application code:

```powershell
docker compose -f compose.supabase.yaml run --rm --build migrate
vercel deploy --prod
```

Vercel Production variables are separate from local `.env`. Re-deploy after a
cloud variable change. Leave local email links at localhost; cloud
`UDHAAR_PUBLIC_URL` must be `https://udhaar-mvp.vercel.app`. Previously delivered
messages keep their original links. Never push `.env`, `.env.local`, `.vercel`,
database files, backups, or private logs. `.vercelignore` uploads only runtime
files, including the versioned privacy/terms/license documents.

## Verify a release

1. Confirm `/api/health` returns `{"ok": true, "app": "udhaar"}`.
2. Open `/`, `/signup`, `/privacy`, `/terms`, `/rights`, and `/license` in a signed-out browser.
3. Verify `/api/inbox` and `/api/records` reject anonymous access.
4. Sign in using a real code, reload, and confirm persistence/logout.
5. When testing delivery intentionally, verify an existing recipient's inbox and
   a guest email/link, then complete both handover and return acknowledgment.
6. Check the email origin, public link access on another device, and mobile layout.

Automated provider tests simulate sending and do not validate real mailbox
delivery. A successful Resend API response means provider acceptance, not proof
that the recipient read or received the message.

## Monitoring and troubleshooting

| Symptom | Check |
| --- | --- |
| App 500/startup failure | Vercel build/function logs, required variables, database revision, pooler/TLS reachability |
| Public app or guest link asks for a Vercel login | Project deployment protection and stable production domain |
| Missing sign-in code | Supabase Auth logs, SMTP settings, template, Resend delivery and quotas |
| Missing invite/acknowledgment email | Resend API key/sender, delivery logs, suppressions, public URL |
| Recipient sees nothing in inbox | Exact recipient email/profile at send time, request state/expiry; later signup does not claim old guest requests |
| HTTP 429 | `Retry-After`, [Auth limits](auth-rate-limits.md), provider usage, or regular invite allowance |
| Wrong database/records | Runtime URL/schema; hosted Docker shares cloud data while local PostgreSQL does not |
| Cookies fail on local HTTP | Hosted secure-cookie setting was copied into the local process |

Restrict operational log access. Request paths and provider email records can
include bearer links, emails, and other personal data. Application upstream error
messages are sanitized, but provider/platform logs have their own capture rules.
Do not paste raw logs into public issues. Rotate exposed database/sending secrets,
replace exposed loan requests, and assess affected data after an incident.

## Backups and recovery

Check the Supabase plan's actual backup/export availability. Do not assume free
hosting includes a recoverable backup. Keep access-controlled copies and test
restoration into a separate database before relying on a backup strategy.
An application-schema dump alone does not include Supabase Auth accounts or
provider configuration; document how profile/identity mappings will be restored.

For the isolated Docker PostgreSQL database, an example local SQL export is:

```powershell
New-Item -ItemType Directory -Force backups | Out-Null
docker compose -f compose.yaml exec -T db pg_dump -U udhaar -d udhaar --file=/tmp/udhaar-backup.sql
docker compose -f compose.yaml cp db:/tmp/udhaar-backup.sql backups/udhaar-backup.sql
```

Backups contain private data and are ignored by Git. Protect them, record their
date/scope, and set a retention schedule. Avoid shell redirection that can change
SQL-file encoding on Windows. Restore with PostgreSQL tools against a separate
test database, check record counts and identity links, and never test restoration
over the live database. Keep schema migrations compatible with both the deployed
code and the backup you would restore.

## Privacy and account requests

The public notice uses the owner's GitHub profile/contact options. A public issue
may request a private channel, but must not contain account information. Arrange
private verification before handling a request; GitHub identity alone does not
prove ownership of an Udhaar email account.

1. Establish the requester's identity, relevant email/profile IDs, requested
   scope, applicable deadlines, and any other person's rights or retention needs.
2. For access/export, collect only data the requester is entitled to: relevant
   profile/identity information, contacts/records, invitations, returns, and events.
   Exclude credentials, token hashes, other users' private notes, and unrelated data.
3. For corrections, review shared/acknowledged records separately. Do not silently
   rewrite terms another person has acknowledged or merge profiles by email.
4. For deletion, review both records owned by the requester and invitations
   addressed to them in someone else's records. Determine what should be removed,
   anonymized, retained, or revoked, and communicate any exception.
5. Execute approved removals in a reviewed transaction respecting all foreign
   keys. Child invitations/returns/events/item extensions depend on records;
   contacts, app-invite history, recipient references, identity mappings, and local
   sessions can depend on users. Removing an Auth account alone does not remove
   application data. Coordinate app-profile removal and Supabase Auth revocation.
6. Verify remaining access paths and send exports/outcomes through the verified
   private channel. Document backup/provider retention limitations. Do not retain
   an unnecessary extra copy of the exported data.

These are manual procedures, not automated export/deletion features. No blanket
deletion deadline or instant backup erasure is claimed by the app. Follow applicable
law and explain the scope and timing of an individual request.

## Current limits

- Public testing uses Vercel Hobby; personal/non-commercial and usage restrictions
  still apply. Supabase and Resend have separate quotas and availability limits.
- FastAPI's OTP limiter is process-local; Supabase's provider limits still apply.
  A distributed limiter and trusted proxy/client-IP handling are future work.
- The database runtime uses table-owner credentials. A restricted runtime role
  and separately scoped migration credentials remain a hardening step.
- Invitation/recipient flows lock shared records, but broad concurrent-return and
  load scenarios still need dedicated stress testing.
- There is no automated archival/retention purge, self-service account deletion,
  data export, reminder scheduler, or account/profile editing workflow.
- Source-code rollback does not roll back database or provider state. Security
  migrations intentionally refuse an automatic downgrade.

Review the notice whenever actual collection, providers, retention, tracking, or
request channels change. The policy text is operational documentation; it is not
a claim of certification or universal regulatory compliance.
