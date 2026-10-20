# Email invitations and loan acknowledgments

## Configure delivery

Supabase continues to send sign-in codes using your configured Resend SMTP account.
The app uses Resend's transactional API for regular invitations and guest loan
acknowledgments. This keeps guest links usable without creating an Auth account.
Supabase's Auth admin invitation API would create an unconfirmed authentication
user, which is unnecessary for these invitations.

1. In Resend, open **API Keys** and create a key with permission to send emails
   from your verified domain. Put the key in the local `.env`, never in frontend
   JavaScript or a checked-in file.
2. Set these variables in `.env`:

   ```dotenv
   RESEND_API_KEY=re_your_key
   UDHAAR_EMAIL_FROM=Udhaar <invites@your-verified-domain.com>
   UDHAAR_PUBLIC_URL=https://your-app.example.com
   ```

   Use the app's origin without a path. Both `/signup` and `/share/...` must be
   reachable there. `http://localhost:8001` is accepted for same-computer tests;
   it will not work for recipients on other computers.

3. Rebuild and start the hosted Compose stack:

   ```powershell
   docker compose -f compose.supabase.yaml up --build -d
   docker compose -f compose.supabase.yaml logs --tail 50 migrate app
   ```

   Its migration service applies `0003_email_invitations` before the app starts.
   For the local Postgres stack, use `compose.yaml` instead.

## Behavior

- **Invite friends** sends a regular signup invitation. Two slots per sender per
  UTC calendar day are enforced by unique database constraints and a slot check.
  Reservations are committed before sending, so provider timeouts or app crashes
  cannot bypass the cap. Failed/uncertain sends appear with **Retry delivery**;
  retries reuse the same invitation and provider idempotency key for up to 23 hours.
  The UI shows the reset time in the viewer's timezone.
- **On the Record** creation and conversion require a validated, normalized
  email. The app checks its `users` profiles by email. Existing users receive an
  account-bound request in **Acknowledgments**, including both accept/decline and
  return handling. Other users and anonymous requests cannot access that inbox.
- A recipient with no app profile receives a private 30-day link by email. It
  supports handover acknowledgment and subsequent returns without signing in.
  Registration is optional in both the email and guest page. Guest actions are
  labeled as identity unverified in the owner history.
- Acknowledgment deliveries are independent of regular invitation quotas. Resend
  account quotas and provider throttling may still restrict actual sending.
- Replacing a request revokes its predecessor and resets handover acknowledgment.
  If the email provider rejects a guest delivery, the database transaction rolls
  back, preserving the previous request. An email accepted by the provider just
  before a database failure may still be delivered with an unusable link; the
  sender can create a new request. Sending acceptance is not proof of inbox delivery.
- Private notes and activity history are excluded from recipient views. Contacts
  with different emails stay distinct even if their names match. Existing contacts
  are not silently reassigned when a different email is entered for sharing.
- Signing up after an anonymous link was emailed does not automatically attach
  that loan to the new account. The link remains usable, or the owner can send a
  replacement request to the newly registered account.

## Database changes

`app_invitations` stores regular invitation reservations, delivery status, and
Resend message IDs. `invitations` adds `recipient_email`, `recipient_user_id`, and
`delivery` (`LINK`, `EMAIL`, or `IN_APP`). Old guest links remain valid after the
migration. The new table has the same private schema, role restrictions, and RLS
boundary as the existing application tables. Supabase's managed `auth` schema is
not modified.

## Check delivery

Use **Resend → Emails** for delivery/bounce details. Inspect regular invitation
history in Supabase SQL Editor:

```sql
SELECT email, invite_day, slot, state, message_id, created_at
FROM udhaar.app_invitations
ORDER BY created_at DESC
LIMIT 100;
```

Inspect acknowledgment routing:

```sql
SELECT record_id, recipient_email, delivery, state, expires_at
FROM udhaar.invitations
ORDER BY created_at DESC
LIMIT 100;
```

References: [Resend sending API](https://resend.com/docs/api-reference/emails/send-email),
[Resend idempotency](https://resend.com/docs/dashboard/emails/idempotency-keys),
[Supabase Auth invites](https://supabase.com/docs/guides/auth/users#inviting-users).
