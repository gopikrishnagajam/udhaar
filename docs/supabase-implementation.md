# Authentication setup and sessions

## Hosted sign-in

The public app and hosted-data Compose stack use Supabase email codes. An app
profile is provisioned after successful verification and linked to the provider
issuer/subject. A contact is not automatically a registered profile. No Supabase
admin key or service-role key is required by the app.

1. In Supabase, enable email authentication and configure custom SMTP using Resend
   credentials for a verified sender. Authentication emails are sent by Supabase
   through Resend SMTP.
2. Set the email template to include the one-time code, for example
   `Your Udhaar sign-in code is {{ .Token }}`. The UI accepts a 6-10 digit code.
   The configured template and expiry must match the provider's actual settings.
3. Set `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` in the backend environment.
   Never replace the publishable key with a server secret key.
4. Use `UDHAAR_AUTH_PROVIDER=supabase`. Docker passes `.env` values into the app;
   Vercel has its own Production environment variables.

The UI requests `/api/auth/otp`, verifies through `/api/auth/verify`, and loads the
profile through `/api/me`. Supabase creates an Auth account only when signup is
requested. Existing-account signup is rejected locally before sending another
code. A provider email-address collision with a legacy local account requires
manual account migration; app records are not reassigned by email.

## Tokens and validation

| Cookie | Access | Scope and lifetime |
| --- | --- | --- |
| `udhaar_sb_access` | HTTP-only | `/`; provider's access-token lifetime |
| `udhaar_sb_refresh` | HTTP-only | `/api/auth`; browser cap 14 days; provider controls validity |
| `udhaar_csrf` | Browser-readable | `/`; session cookie matched by mutation headers |
| `udhaar_session` | HTTP-only, local mode only | `/`; hashed DB session, 14 days |

Hosted cookies use `Secure` and SameSite=Lax. Tokens are not returned to frontend
JavaScript or stored in web storage. Normal protected requests verify JWT
signature and issuer/audience/expiry/subject/role claims using cached Supabase
public keys. ES256 and RS256 are supported; unsigned and HS256 tokens are rejected.
Verification and refresh also validate provider user information over HTTPS.

On a protected API 401, the frontend attempts a single refresh and retries once.
Parallel requests in one tab share the refresh promise. A permanent refresh
failure clears the signed-in UI; a provider outage/rate limit retains its status
and explanation. Different browser tabs still refresh independently.

Logout clears browser sign-in cookies and attempts to revoke that device's
Supabase session, using the refresh token if the access token is stale. Local
signout still succeeds when the provider is unavailable. Issued access tokens
may remain usable until expiry; immediate provider revocation is not checked on
every locally verified JWT request.

Supabase-managed sessions can be inspected in SQL Editor without displaying
tokens:

```sql
SELECT s.id, u.email, s.created_at, s.updated_at
FROM auth.sessions s
JOIN auth.users u ON u.id = s.user_id
ORDER BY s.created_at DESC
LIMIT 100;
```

A session row is not an online-presence indicator. An empty `udhaar.login_sessions`
table is expected when using Supabase Auth.

## Local password mode

`UDHAAR_AUTH_PROVIDER=local` enables `/api/register`, `/api/login`, and `/api/logout`
for isolated development. Passwords use Argon2; session tokens are hashed in
`login_sessions`. Production configuration refuses this mode. Switching providers
does not automatically convert accounts or transfer profiles/records.

## Troubleshooting and tests

- Code missing: inspect Supabase Auth logs and Resend delivery records. Check SMTP
  credentials, verified domain/sender, template, suppression/bounce state, and quotas.
- HTTP 429: respect `Retry-After`; see [rate limits](auth-rate-limits.md).
- Session disappears on local HTTP: secure cookies require HTTPS; local Compose
  sets them false while Vercel sets them true.
- Browser APIs unavailable: inspect `/api/auth/config`, `/api/health`, and server
  logs. Never paste full cookies or provider responses into public issues.

`tests/test_supabase_auth.py` simulates the provider at the HTTP boundary and uses
signed test JWTs. It covers profile stability, account isolation, cookie rotation,
invalid claims, rate limits, outages, and anonymous loan completion without
sending real email. Browser session checks run against a configured Supabase-mode
app:

```powershell
npm ci --prefix tests/browser
$env:UDHAAR_TEST_BASE_URL='http://localhost:8001'
node tests/browser/sessions.cjs
```

The default browser is installed Microsoft Edge. Override
`UDHAAR_TEST_BROWSER_CHANNEL` or `UDHAAR_TEST_BROWSER_PATH` when needed. Real
delivery, multi-device revocation, and multi-tab refresh races need provider-level
testing in addition to simulated regressions.

References: [Supabase email OTP](https://supabase.com/docs/guides/auth/auth-email-passwordless),
[SMTP](https://supabase.com/docs/guides/auth/auth-smtp),
[sessions](https://supabase.com/docs/guides/auth/sessions).
