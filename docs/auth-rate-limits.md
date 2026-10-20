# Authentication and email limits

Several independent limits apply. A restart does not reset Supabase or Resend
quotas, and the two daily app invitations are unrelated to sign-in codes or loan
acknowledgment emails.

| Layer | Current behavior |
| --- | --- |
| Browser | Submit guards and per-email send/resend countdown; verification honors retry timing. Reloading clears only this UI state. |
| FastAPI process | Bounded in-memory attempt windows keyed by email and apparent client IP. Not shared across Vercel instances or restarts. |
| Supabase Auth | Provider cooldowns and project/IP/token limits configured in the project dashboard. |
| Resend | Sender account daily/monthly quotas, API throttling, suppression, and delivery policy. |
| Regular app invites | Database-enforced two slots per sender per UTC day, shared across instances and persistent across restarts. |

## Process guards

The backend tracks rolling 60-second windows:

- OTP sends: one per email and five per apparent client IP.
- OTP request/precheck and verification attempts: ten per email/IP action window.
- Entries are bounded to avoid unlimited process memory growth.

The backend currently uses the connecting client address without forwarding a
browser-supplied IP header to Supabase. Proxy/shared addresses can aggregate
users. This process-local guard is a small-test deployment measure; a global
distributed limiter and trusted proxy configuration remain operational work.

## Provider limits and errors

Check **Supabase → Authentication → Rate Limits** for the project's actual values.
Auth requests and email sends have different limits. Provider HTTP 429 remains
429; a valid numeric `Retry-After` is preserved. The UI uses the provider timing
when available, and a fallback countdown otherwise. It does not auto-send when a
timer ends. A longer project quota can outlast the displayed fallback timer.

Supabase sign-in emails travel through Resend SMTP. Regular invitations and
guest acknowledgment emails use Resend's API directly. API throughput and SMTP
sending quotas are different controls, but both paths use the sending account's
allowance. Existing-user inbox acknowledgments do not send an email.

## Regular invitation reservation

`app_invitations` reserves one of two unique daily slots before contacting the
email provider. A failure or timeout keeps the slot so uncertain delivery cannot
allow a third message. Retry uses the same invitation/key for up to 23 hours;
it does not consume another slot. The UI displays the next UTC reset in local
time. Guest loan acknowledgments never consume these regular-invite slots.

See [email invitations](email-invitations.md) for retry and delivery behavior.

## Diagnose in order

1. Read the HTTP status and `Retry-After`, then wait rather than retrying rapidly.
2. Inspect Supabase Auth logs for provider code-send/verification failures.
3. Inspect Resend delivery status, sender/domain settings, suppressions, and usage.
4. Inspect Vercel application logs for sanitized upstream error codes.

Do not publish provider responses, cookies, full request URLs, sign-in codes,
or guest links. Tests simulate provider limits and do not send real email.

References: [Supabase Auth limits](https://supabase.com/docs/guides/auth/rate-limits),
[Resend limits](https://resend.com/docs/api-reference/rate-limit).
