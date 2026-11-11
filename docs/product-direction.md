# Product direction

Udhaar is a personal and shared ledger for things people lend, borrow, owe, and
return. It records arrangements people have already made and helps them review
what remains outstanding and what has been acknowledged.

The intended audience is people in the United States managing everyday
arrangements with friends, family, colleagues, and other known contacts.
A shared expense ledger is a useful analogy, but Udhaar extends the record
beyond money and does not require complex expense splitting.

## Core experience

A person records what they lent or borrowed, who was involved, and relevant
dates or notes. They can keep the entry private or share it for acknowledgment.
The record continues through handover, partial returns, and final receipt.

Planned paid-lending records add the agreed rental charge and a history of money
received outside Udhaar. For example, a lender could record a camera rental for
$40, log $20 received, and see $20 remaining. An item being returned does not
establish that its rental charge has been paid.

## Current and planned capabilities

| Capability | State |
| --- | --- |
| Physical item records, quantities, dates, notes, and contacts | Implemented |
| Private records and shared handover acknowledgment | Implemented |
| Account inboxes and guest acknowledgment links | Implemented |
| Partial returns and lender confirmation | Implemented |
| Record activity timeline | Implemented |
| Paid lending and rental charges | Planned |
| Entries for externally made payments and refunds | Planned |
| Rental receipt summaries and earnings history | Planned |
| General money records and balances | Broader direction; no implementation scope selected |

## Visibility and acknowledgment

**Off the Record** means a private ledger entry visible to its owner through
ordinary user APIs. The owner records their own updates and returns.

**On the Record** means an arrangement is shared with the other person for
acknowledgment. An existing account receives an in-app request. A guest receives
a private bearer link. An accepted guest action establishes access to that link,
not independently verified identity.

Free versus paid describes the arrangement. Private versus shared describes
visibility and acknowledgment. These are independent choices.

## Status and history

Use separate states for separate events:

- A handover can be pending, accepted, or declined.
- An item can be outstanding, partially returned, or fully returned.
- A planned payment entry can be reported or acknowledged as received.
- A planned charge can be unpaid, partly paid, or settled.

The current shared-return flow already distinguishes a borrower's report from a
lender's confirmation. Payment acknowledgment rules are a design proposal to
resolve before payment records ship, not an implemented payment workflow.

A zero balance is a calculation from charges and payment entries. It must not
mean the original arrangement or its history was deleted. Corrections should
remain understandable through the record history, subject to retention and
verified privacy requests. The current system is not an immutable legal archive.

## Paid lending scope

Udhaar will record payments made outside the application. It will not receive,
hold, transfer, or escrow rental payments, and the agreed feature takes no
commission. Payment entries are user reports; do not label them bank-verified.

The first pricing model, deposits, and earnings export format remain open.
A fixed total in USD is the recommended starting point. Daily/weekly pricing
requires explicit rules for duration, rounding, partial returns, and extensions.
Refundable deposits need separate balances rather than being included
automatically in rental receipts.

Use precise monetary storage and distinguish agreed charges, receipts, refunds,
and remaining balance. Receipts are not automatically profit or taxable income.

## Scope boundaries

The agreed experience does not include public item listings, discovery, matching,
booking, payment collection, debt collection, or complex group expense splitting.
Money lending, interest, automated penalties, and generated legal agreements
require separate product and legal decisions.

## Product principles

1. Make it easy to record an existing arrangement.
2. Explain who entered an action and who acknowledged it.
3. Preserve the distinction between a report and a confirmation.
4. Keep private notes out of recipient views.
5. Keep historical records understandable when an arrangement is settled.
6. Measure speed on real journeys and avoid unnecessary recurring database work.
