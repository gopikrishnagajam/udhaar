# Privacy notice

Effective October 19, 2026.

Udhaar is an item lending and borrowing tracker operated for public testing by
[Gopi krishna Gajam](https://github.com/gopikrishnagajam). This notice covers
the hosted app at https://udhaar-mvp.vercel.app. Operators of other deployments
are responsible for their own data practices and contact details.

## Information we handle

- **Account information:** name, email address, account identifiers, and the link
  between your app profile and Supabase authentication identity. Supabase handles
  email-code authentication. The hosted app does not use a password;
  development accounts created in local password mode store an Argon2 password hash.
- **Loan information:** contact names and optional emails, item descriptions,
  quantities, dates, private notes, acknowledgment state, returns, and activity
  timestamps. A registered user may enter your details as a contact even if you
  have never registered. In that case, the record owner is the source of the data.
- **Invitations:** sender and recipient details, delivery status, provider message
  IDs, expiry times, and hashes of loan-link tokens. The actual guest link is
  included in its email and is available to anyone who receives or forwards it.
- **Service information:** the hosting, authentication, and email providers may
  process IP addresses, browser/request information, sign-in events, request paths,
  and delivery/bounce logs. Logs and email copies may contain private links.

## Why we use this information

We use it to sign you in, keep the records you create, deliver invitations,
request acknowledgments, track returns, enforce limits, prevent misuse, and
investigate service problems. Email and authentication data are necessary for
an account; recipient email is necessary when requesting a shared acknowledgment.
Private notes and optional due dates are not required.

Where data protection law requires a processing basis, account and loan services
support the service you request; security and delivery checks support the
legitimate interests of operating a reliable service. Processing contact details
supplied by another user supports that user's requested record and acknowledgment
flow. You can object to that use or dispute an invitation through the contact
process below. Applicable legal obligations may also require limited retention.

The application does not sell personal data, run advertising, or include an
advertising/analytics tracking script. Dashboard totals are calculated from your
records. The app does not make automated credit, eligibility, or lending decisions.

## Who can see information

- **Off the Record:** other ordinary users cannot view your private records.
  Authorized operators and infrastructure providers can access stored data as
  needed to operate and support the service. Records are not end-to-end encrypted.
- **On the Record:** the intended registered recipient can review the shared
  loan and act on its acknowledgment and returns. A guest link grants equivalent
  access to its holder without an account. Recipient views omit the owner's
  private notes, contact email, and internal activity timeline.
  The sender can see whether a request was routed to an app inbox or by email.
- **Email recipients:** the recipient and their email provider receive the
  invitation message. Forwarding an acknowledgment link grants its bearer access
  until the request expires or is replaced. You cannot recall a delivered email
  or erase a recipient's saved copy through Udhaar.

We use [Vercel](https://vercel.com/legal/privacy-notice) to run the app,
[Supabase](https://supabase.com/privacy) for its database and authentication,
and [Resend](https://resend.com/legal/privacy-policy) for email delivery. These
providers and their subprocessors handle the data needed for their roles. Data
may be processed outside your country, including in the United States, according
to the configured regions and provider arrangements. There is no promise that
all data remains in your country. Applicable transfer safeguards and contractual
details can be requested from the operator.

## Cookies and browser storage

The app uses essential cookies for sign-in and request protection:

- `udhaar_sb_access`: an HTTP-only access token, valid for the provider's token lifetime.
- `udhaar_sb_refresh`: an HTTP-only refresh token scoped to `/api/auth`, with a
  browser persistence cap of 14 days; Supabase controls actual session validity.
- `udhaar_csrf`: a browser-readable session cookie used to protect changing requests.
- `udhaar_session`: used only by local password authentication, with a 14-day expiry.

Hosted sign-in cookies use HTTPS and SameSite protections. Signing out clears the
app's sign-in cookies and attempts to revoke that device's Supabase session. It
does not delete account or loan data. Clearing or blocking cookies can prevent
sign-in. The frontend does not store authentication tokens in localStorage or
sessionStorage. Infrastructure may use additional security cookies under its own
notice.

## Retention and deletion

Account profiles, contacts, loans, returns, and invitation/activity history are
kept to support your account and record history until the operator removes them
following a verified request or an operational cleanup. There is currently no
automatic age-based purge. A guest link stops working after 30 days or replacement;
expiry does not erase the underlying record or invitation row.

Provider logs, backups, and delivered email copies follow their own configured
retention. Removing live records does not instantly remove backup or recipient
copies. Any delay, other person's rights, or legal reason affecting a deletion
request will be explained. No fixed deletion or backup-erasure period is promised
by the app. Account deletion and data export currently require manual assistance.

## Your choices, requests, and complaints

You can use private records, decline an acknowledgment, avoid registering when
using a guest link, stop using the app, and request access, correction, a copy of
your data, or deletion. Depending on applicable law, you may also have rights to
object to processing, restrict it, withdraw consent where processing relies on
consent, or complain to your local data protection authority. These rights can
have exceptions; another user's legitimate records may require separate review.

Use the contact options published on the operator's
[GitHub profile](https://github.com/gopikrishnagajam). If no suitable private
contact is listed, open a [repository issue requesting a private contact
channel](https://github.com/gopikrishnagajam/udhaar/issues/new?title=Private%20privacy%20contact%20request).
State only that you need private contact. **Do not post your email address,
loan details, passwords, sign-in codes, or guest links in a public issue.**
Someone who shared a loan with you can also help put you in touch with the operator.
Identity and the scope of the request will be verified privately before data is
disclosed or removed. Statutory response requirements apply where relevant.

## Changes

The effective date above identifies this notice. Material changes will be
published on this page. See also [Terms of use](TERMS.md) and
[Rights and licensing](RIGHTS.md).
