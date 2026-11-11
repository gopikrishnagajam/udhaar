# Development roadmap

The current priority is a responsive, dependable ledger on the existing
Vercel and Supabase development deployment. Hosting migration follows the
development phase.

The local production backlog uses stable IDs PT-001 onward. Its statuses and
public retest evidence remain authoritative for those reports; this roadmap
makes priorities available in the tracked repository.

## Stabilize the current beta

| Area | Backlog | Release evidence still needed |
| --- | --- | --- |
| Unknown-email sign-in | PT-001 | Real-email signup and existing-user sign-in |
| In-app recipient routing | PT-002 | Correct account, no existing-user acknowledgment email |
| Recipient dashboard visibility | PT-003 | Two-account receipt, reload, accept/decline, and returns |
| Email delivery latency | PT-004 | Real-mailbox timings separating provider acceptance from delivery |
| Page performance | PT-005 | Authenticated before/after journey timings on public mobile and desktop |

Local regression success does not close a public acceptance item.

Performance investigation should separate browser work, API time, database
connection/query time, provider calls, and function startup. The local identity
lookup optimization uses one joined query instead of two per normal authenticated
request; its public improvement still needs measurement.

Continue checking unpaginated record histories, recurring inbox polling,
concurrent return updates, and email delivery inside write transactions.
Validate those paths against current code and realistic workloads; prior local
fixes do not replace public acceptance.

## Add paid lending records

PT-006 covers lender-created rentals and earnings history. The agreed scope is
a ledger of arrangements made by users, with payment records entered manually
for money exchanged outside Udhaar. It does not include payment processing or
a marketplace.

Implementation should extend existing records and preserve free lending.
Acceptance needs migration compatibility, exact monetary arithmetic, correct
partial payment/refund totals, account isolation, clear receipt attribution,
independent return/payment status, and history that survives settlement.
Do not fetch complete payment histories on every inbox poll.

Resolve these decisions before committing the financial data model:

- Fixed-total versus daily/weekly pricing, currency, and rounding.
- Whether refundable deposits are included.
- Who can report, confirm, dispute, and correct shared payment entries.
- How changing agreed charges affects prior acknowledgment.
- What earnings summaries and exports include.

## Prepare for broader release

Review the operator's actual location and intended use, the privacy notice,
terms, private contact channel, retention, deletion/export handling, and backup
recovery. [Legal considerations](legal-considerations.md) records the research
without treating it as nationwide clearance.

The current table-owner database connection and process-local rate limiter remain
operational constraints. Review a restricted runtime role, abuse handling,
restore testing, and load/concurrency behavior before increasing exposure.

## Move hosting after development

The agreed target is approximately $15 per month, serving a US audience.
The preferred design is a US VPS running the app and PostgreSQL together,
with Supabase Auth retained initially. This is a future deployment direction,
not an existing production configuration or a guaranteed provider quote.

Before moving, measure representative journeys, select a region, prepare HTTPS
and off-server backups, test migration/restore, and plan cutover and rollback.
Previously sent guest links retain their old origin and need a continuity plan.

## Repository documentation cleanup

The cleanup replaces the stale review report with current priorities, removes
unused sample previews, and consolidates the dependency entry point. Topic-based
architecture, authentication, and database guides replace provider-specific
filenames. The runtime policy documents, migrations, tests, operational guides,
and local production-feedback history remain maintained.
