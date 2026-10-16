# Udhaar — runnable MVP

**Udhaar** is a responsive lending-and-borrowing tracker: "Lend it. Track it. Get it back."

This is a **working local MVP**, not a deployment-ready commercial product. It tracks **physical items** first while keeping a shared `Record` / item-specific `ItemLoan` model suitable for a future `MoneyLoan`. The current package has **no AI features, payment features, product recommendations, data resale, or analytics tracking**.

## What is included

- Supabase email-code signup/sign-in in Docker, with local profiles and HTTP-only auth cookies; explicit local development mode retains email/password authentication.
- **Off the Record**: default private lending and borrowing records; users can update notes, due dates, and item names and mark items returned without inviting anyone.
- **On the Record**: optional invitations via private links; the other person can acknowledge or decline without a separate account. Sent ≠ accepted.
- **Return tracking**: partial returns; either party can propose. Only the **lender** may confirm a shared return. Privately recorded returns are marked complete by the owner.
- **Independent states**: `acknowledgment` (`NONE`, `PENDING`, `CONFIRMED`, `DECLINED`) is separate from settlement (`OUTSTANDING`, `PARTIAL`, `RETURNED`).
- Searchable dashboard, lent/borrowed counts, overdue indicators, record activity history, mobile-responsive UI.
- Invitation links expire after 30 days. Generating a replacement revokes prior links and requires fresh acknowledgment.
- Per-account authorization and CSRF checks; API tests cover both local and Supabase authentication.

## Local Docker + PostgreSQL (recommended)

Start Docker Desktop using Linux containers. On first setup, copy `.env.example`
to `.env` and replace `POSTGRES_PASSWORD` and `PGADMIN_PASSWORD` with separate random URL-safe passwords. If
`.env` already exists, keep it and add any missing Compose variables.

```powershell
docker compose up --build -d --wait
docker compose ps
```

Open **http://localhost:8000**. Compose builds the Python app with the PostgreSQL
driver, waits for PostgreSQL to be healthy, and creates the application tables on
the first startup. `/api/health` checks the application's database connection.
Both ports are bound to localhost: app `8000`, PostgreSQL `5432`. Change `APP_PORT`
or `POSTGRES_PORT` in `.env` if needed. Inside Compose, the database host is `db`.

### Inspect PostgreSQL with pgAdmin

Compose also starts **pgAdmin at http://localhost:5050**, bound to localhost.
Sign in with `PGADMIN_EMAIL` (default `admin@example.com`) and `PGADMIN_PASSWORD`
from your local `.env`. Change `PGADMIN_PORT` if port 5050 is in use.

The **Docker > Udhaar local PostgreSQL** server is already registered. Open it
and enter `POSTGRES_PASSWORD` from `.env` when prompted for the database password.
This is separate from your pgAdmin login password. Select **Databases > udhaar**:

- **Schemas > public > Tables** contains the application tables. Right-click a
  table and select **View/Edit Data > All Rows** to inspect its records.
- **Dashboard** shows database activity and connections.
- **Tools > Query Tool** lets you run SQL, for example `SELECT * FROM records;`.

pgAdmin settings persist in the separate `pgadmin_data` volume. Its login settings
initialize on first launch; changing `.env` later does not reset an existing login.
Database host `db` works inside the Docker network; desktop database clients use
`localhost` with `POSTGRES_PORT` instead.

### Data and tests

Data lives in the `postgres_data` named volume and survives container restart,
recreation, and `docker compose down`. This starts a separate database: existing
`udhaar.sqlite3` data is not imported. Docker defaults to Supabase email-code
authentication. Set `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` in `.env`, configure
the Supabase email-code template, then recreate the app. See the full
[Supabase implementation guide](docs/supabase-implementation.md) for architecture,
flow diagrams, setup, code changes, and manual test steps. Supabase stores
authentication identities; profiles and loan data remain in local PostgreSQL.
Set `UDHAAR_AUTH_PROVIDER=local` explicitly to use the earlier password-based
development mode. There is no automatic fallback between modes.

Run the API suite against PostgreSQL (each test uses a temporary isolated schema):

```powershell
docker compose --profile test run --build --rm tests
```

Run a real HTTP smoke test against the running app:

```powershell
python scripts/smoke_test.py http://localhost:8000
```

The password smoke test requires local authentication mode. It creates a test account
and a completed loan, retained for inspection.
It covers registration, login/logout, anonymous handover acknowledgment, return
acknowledgment, and private-note isolation.

```powershell
docker compose logs --tail 50 app db
docker compose exec db psql -U udhaar -d udhaar
docker compose down
```

Avoid `docker compose down -v` unless you intend to delete the local database.
`POSTGRES_PASSWORD` initializes a new volume; changing it later in `.env` does not
change an existing database password. Application schema changes still need
migrations before production; `create_all` only creates missing tables.

## Quick start without Docker (SQLite)

Requires **Python 3.10+**. Run the following from this folder:

```bash
python -m venv .venv
# macOS / Linux:
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Then open **http://127.0.0.1:8000** and create an account. You can add your first item right away; no frontend build, Node.js, or external API key is needed. The app creates `udhaar.sqlite3` automatically and keeps the records across restarts. API documentation is at `http://127.0.0.1:8000/api/docs`.

### Try the hybrid workflow

1. Register an account and create a **Lent** record for a tool with **Off the Record** selected.
2. View it on the dashboard, edit its details, and explore private return tracking.
3. Create a second record, open the record, and choose **Move to On the Record** or choose On the Record at creation.
4. Generate a share link. In a separate browser/private window, paste the link to act as the recipient.
5. Acknowledge the loan. The borrower can then report a return; the lender confirms it in the original account. (For records created with **Borrowed** direction, the guest acts as the lender.)

**Note:** Acknowledgment confirms only that someone with the invitation link responded. It is *not* verified identification, legal proof of a debt, or confirmation of a payment.

## Tech choices

| Layer | Implementation |
|---|---|
| Backend | FastAPI (Python), JSON REST endpoints |
| Database | SQLAlchemy models, SQLite for local development |
| Frontend | Responsive HTML + vanilla JavaScript + CSS; no build step |
| Authentication | Supabase email OTP with server validation, HTTP-only token cookies, local identity mapping, CSRF checks; optional legacy local password mode |
| Sharing | Opaque random bearer invitation token; only its SHA-256 hash is stored |
| Optional later database | PostgreSQL via `UDHAAR_DATABASE_URL` with `requirements-postgres.txt` |

**Why not Django/React yet?** The agreed early design suggested Django REST Framework + React/TypeScript. For this runnable artifact we used a lightweight server and no-build frontend, since this execution environment cannot fetch those dependencies. This is a pragmatic MVP implementation, not a change to the product architecture commitment. A Django/React production rebuild can preserve the same models, lifecycle and REST API semantics.

## Core data model

```text
User 1 — * Contact
User 1 — * Record (kind=ITEM, direction=LENT|BORROWED, mode=OFF|ON)
Record 1 — 1 ItemLoan (item name, category, quantity)
Record 1 — * ItemReturn (quantity, proposed by, status, confirmed by)
Record 1 — * Invitation (hashed token, expiry, state)
Record 1 — * RecordEvent (actor, change type, timestamp)
```

When money tracking is introduced later, add a distinct `MoneyLoan` extension (`principal_decimal`, `currency`) and `Repayment` table. Keep settlement logic separate for items and money. Do **not** treat item quantities as money amounts; use decimals and confirmed repayments for monetary balances.

## Main endpoints

- `POST /api/register`, `/api/login`, `/api/logout`, `GET /api/me`
- `GET /api/records`, `POST /api/records`, `GET /api/records/{id}`, `PATCH /api/records/{id}`
- `POST /api/records/{id}/share`
- `POST /api/records/{id}/returns`, `POST /api/records/{id}/returns/{return_id}/confirm`
- `GET /api/share/{token}`, `POST /api/share/{token}/respond`
- `POST /api/share/{token}/returns`, `POST /api/share/{token}/returns/{return_id}/confirm`

Mutating requests require a CSRF token from `GET /api/csrf`. The browser UI handles this automatically.

## Automated tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q tests
```

Tests cover privacy/isolation, acknowledgment, duplicate response rejection, lender-only confirmation, partial returns, outstanding-quantity safeguards, link revocation, declined invitations, invalid dates and CSRF protection.

## Important limits before any public launch

This is a small-group development prototype. Before deployment to untrusted users, add:

- HTTPS, secure cookies (`UDHAAR_COOKIE_SECURE=true`) and correctly configured host/origin restrictions.
- Proper persistent Postgres migrations (Alembic), database backups, transaction isolation/locking for concurrent returns, and safe operational monitoring.
- Email verification for higher-trust acknowledgment; abuse protection, login rate limiting, account recovery and invitation revocation UI.
- Thorough accessibility, end-to-end/browser, security, and load testing; privacy policy, data export/deletion flows and retention rules.
- Invitation-link handling safeguards (they grant bearer access to the specific loan). Sharing identity has not been verified.
- Support for edited acknowledged terms through explicit versioning and renewed acknowledgment; the MVP deliberately locks shared records after an invitation rather than silently rewriting agreed details.

### Future insights and AI

The MVP calculates **personal** counts for the signed-in user. It does not run a background analytics collector. For potential future Udhaar Insights, define item categories and opt-in consent, collect only minimal eligible events, aggregate carefully, and use retention controls to prevent identifying people or reverse-engineering private records. A simple rule-based borrowing-frequency insight should precede any AI product recommendations. **Off the Record records stay hidden from other users**, and no individual notes/contact data should ever be sold as marketing data.

## Directory structure

```text
udhaar_mvp/
  backend/
    main.py       # API, auth, sharing and return business rules
    models.py     # SQLAlchemy data models
  static/
    index.html    # SPA entry point
    app.js        # Client state and views
    style.css     # Responsive layout
  tests/
    test_mvp.py   # API tests
  requirements.txt
  README.md
```

Built as an implementation of our October 2026 Udhaar product conversation.

## Simple sharing

- **Loan links** (`/share/<token>`): anyone holding the link can view and acknowledge the loan without an account, then revisit the same link for returns. The sender is responsible for sharing with the right person; identity is not verified. Borrowers report returns and lenders confirm receipt. Private notes remain hidden. Links expire after 30 days; replacing one invalidates the previous link and requires fresh acknowledgment.
- **App invitations** (`/signup`): use **Invite friends** in the dashboard to copy the signup URL and send it through a messaging app. There is no invitation tracking or automatic delivery.
- Open the app at an address recipients can reach before copying links. Localhost links only work on the sender's computer; LAN IP links require access to that network.

### Two separate acknowledgments

1. **Handover**: the loan-link holder acknowledges "I took / borrowed this item" when the owner lent it, or "I gave / lent this item" when the owner borrowed it.
2. **Return / completion**: the lender acknowledges receipt of returned items. A borrower reporting a return leaves it pending until the lender acknowledges. Partial returns do not complete the loan; all quantities must be confirmed. The handover acknowledgment remains recorded independently.

The API exposes `handover_acknowledgment` and `return_acknowledgment` separately. The existing `acknowledgment` field remains an alias for handover. Return acknowledgment is derived from the saved return records; no extra database migration is needed. Both stages use the same loan link within its existing expiry.
