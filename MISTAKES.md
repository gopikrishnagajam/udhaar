# Code Review & Engineering Post-Mortem (`MISTAKES.md`)

**Reviewer:** Senior Staff Engineer  
**Author:** Junior Engineer  
**Verdict:** **Request Changes (Do Not Ship to Production Beyond Beta)**

---

## Executive Summary

You built a functional MVP with decent test coverage around happy-path security boundaries (CSRF cookies, RLS migrations, HTML escaping via `esc()`, and row-level locking on some endpoints). **Stop patting yourself on the back there.**

Under the hood, this codebase is a masterclass in **"it works on my local SQLite database with 2 rows, so I shipped it."** You have open tickets in [`TODO.md`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/TODO.md) wondering why **pages are slow (`PT-005`)** and why **emails/auth feel sluggish (`PT-004`)**, treating them like mysterious cloud infrastructure riddles. They aren't mysteries. **You caused them in your own code.**

You are serving **2.65 MB of unoptimized PNGs with `Cache-Control: no-store`** on every page load, executing **$1 + 5N$ sequential database queries per inbox load** (and throwing half the fetched data in the trash), holding **database row locks across 15-second external HTTP calls**, and maintaining **hand-minified 2,500-character single-line CSS/JS files** that are impossible to diff or maintain.

Below is the prioritized list of your mistakes. Fix them **strictly in this order**.

---

## Priority 0: Production-Killing Performance & Concurrency Bugs (Fix Immediately)

### Mistake 1: You put `Cache-Control: no-store` on EVERY static asset and shipped a 1.42 MB 36×36px icon
- **Where:** [`backend/main.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L287-L294), [`static/branding/logo.png`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/static/branding/logo.png), [`static/branding/logo-ledger.png`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/static/branding/logo-ledger.png), [`static/app.js`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/static/app.js#L214-L224)
- **What you did:**
  1. Your global HTTP middleware (`security_headers`) unconditionally stamps `response.headers['Cache-Control'] = 'no-store'` on **every response from the server**—including `/static/app.js`, `/static/style.css`, `/static/branding/logo.png`, and `/privacy`.
  2. `static/branding/logo.png` is **1,422,349 bytes (1.42 MB)**, yet you render it at `36x36` pixels (`width="36" height="36"`) and use it as the page favicon! `static/branding/logo-ledger.png` is **1,228,305 bytes (1.23 MB)** rendered at `240x80`.
  3. Worse, every time the user switches a tab or every 30 seconds when `refreshInbox()` runs on the Inbox tab, `topLayout()` nukes `$('#app').innerHTML` and re-inserts two `<img src="/static/branding/logo.png">` tags. Because you forced `Cache-Control: no-store`, the browser is forbidden from caching your 1.42 MB icon!
  4. You also committed the exact same 3 MB of PNG files twice: once in `logo/` and once in `static/branding/`, plus an unused 385 KB `logo-foreground.png`.
- **Order:**
  1. Scope `Cache-Control: no-store` to `/api/*` routes only. Serve `/static/*` with `Cache-Control: public, max-age=86400` (or immutable hashed filenames).
  2. Resize and compress `logo.png` (a 72×72 WebP/PNG or SVG should be **< 5 KB**, not **1.42 MB**) and `logo-ledger.png` (**< 15 KB**, not **1.23 MB**). Delete the duplicate `logo/` directory or keep source assets out of the runtime bundle.

---

### Mistake 2: Catastrophic $O(N)$ / N+1 SQL Query Explosions on Every Dashboard Load (`PT-005`)
- **Where:** [`backend/models.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/models.py#L63-L66), [`backend/main.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L143-L174), [`backend/main.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L200-L207), [`backend/main.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L416-L419), [`backend/main.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L487-L491)
- **What you did:**
  - In [`models.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/models.py#L63-L66), `Record.contact`, `Record.item`, `Record.returns`, and `Record.events` all use SQLAlchemy's default lazy loading (`lazy='select'`).
  - In [`all_records`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L416-L419), you fetch `N` `Record` rows and call `summary(r)` in a list comprehension. For **each** record, `summary(r)` lazy-loads `r.returns` (Query 1), `r.item` (Query 2), and `r.contact` (Query 3). For 25 records, you execute **76 sequential SQL round-trips** to Supabase!
  - In [`acknowledgment_inbox`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L487-L491), it is even more embarrassing:
    ```python
    return [recipient_view(db, inv, db.get(Record, inv.record_id)) for inv in invitations]
    ```
    For **every single invitation**, you run:
    1. `db.get(Record, inv.record_id)` (1 query)
    2. `detail(rec)` -> `summary(rec)` -> lazy-loads `rec.returns`, `rec.item`, `rec.contact` (3 queries)
    3. `detail(rec)` -> lazy-loads `rec.events` (1 query) and sorts them in Python... **and then two lines later in `recipient_view()` ([line 202](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L202)), you do `result.pop('events', None)`!** You literally query the database for all `RecordEvent` rows just to delete them from the dictionary before returning!
    4. `db.get(User, rec.owner_id).name` (1 query)
    That is **$1 + 6M$ sequential network queries** for $M$ inbox items!
- **Order:**
  1. Add `selectinload` / `joinedload` options (`joinedload(Record.contact)`, `joinedload(Record.item)`, `selectinload(Record.returns)`) to `all_records` and `acknowledgment_inbox`.
  2. In `recipient_view()`, call `summary(rec)` + serialize `returns` directly instead of calling `detail(rec)` and popping `events` after triggering a lazy-load query.
  3. Join or batch-load the owner `User` in `acknowledgment_inbox` instead of calling `db.get(User, rec.owner_id)` in a loop.

---

### Mistake 3: Holding Database Transactions and `FOR UPDATE` Row Locks Across 15-Second External HTTP Calls
- **Where:** [`backend/main.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L210-L235), [`backend/main.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L422-L447), [`backend/main.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L476-L484), [`backend/email_delivery.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/email_delivery.py#L27-L46)
- **What you did:**
  - In `create_invitation`, you lock the `Record` row with `SELECT ... FOR UPDATE` ([line 479](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L479)).
  - Then `deliver_record` mutates the DB, calls `db.flush()`, and **while the database transaction and row lock are still open**, calls `email_delivery.send_email(...)`, which makes a synchronous `httpx.post('https://api.resend.com/emails', ..., timeout=15)` call over the internet!
  - Only *after* Resend responds does `create_record` or `create_invitation` call `db.commit()`.
  - You understood why this is terrible when you wrote `send_app_invitation` ([line 319](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L319): *"Commit the daily reservation BEFORE contacting Resend"*), yet you did the exact opposite in `deliver_record`! Holding open a PostgreSQL transaction through Supavisor's transaction pooler (`port 6543`) for up to 15 seconds while waiting on an external HTTP API will exhaust your database pool under load.
- **Order:**
  1. Never hold an open DB transaction or `FOR UPDATE` lock across an external HTTP call to Resend.
  2. Persist the `Invitation` state (or use an outbox/pending-delivery state), commit the transaction, send the email outside the DB transaction, and handle failure cleanly.

---

### Mistake 4: Broken IP Rate Limiting Behind Vercel / Reverse Proxies (`request.client.host`)
- **Where:** [`backend/supabase_auth.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/supabase_auth.py#L207-L226)
- **What you did:**
  - In `limit_attempts`, you rate-limit by `('request', 'ip', request.client.host if request.client else 'unknown')` and `('send', 'ip', request.client.host ...)`.
  - Behind Vercel or a container reverse proxy without trusted proxy header extraction, `request.client.host` is the internal proxy IP (or `127.0.0.1`), NOT the end user's IP.
  - Because all requests to a warm function instance share that same `request.client.host`, **5 OTP sends across ANY 5 users within 60 seconds** (or 10 email existence checks across any users) will lock out **every single user hitting that instance** with `429 Too Many Requests`!
  - Conversely, across cold/parallel serverless instances, `_attempts` is process-local memory and provides zero distributed protection.
- **Order:**
  1. Extract the real client IP safely on Vercel (`x-real-ip` / `x-forwarded-for` only when `VERCEL == '1'` or behind a configured trusted proxy), or move rate-limit counters to the database / Redis.

---

### Mistake 5: Race Condition on Owner Return Creation (`add_return` Missing Row Lock)
- **Where:** [`backend/main.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L137-L141), [`backend/main.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L257-L272), [`backend/main.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L522-L533)
- **What you did:**
  - When a guest or inbox recipient records a return, `available_invitation()` locks the `Record` row with `.with_for_update()` ([line 184](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L184)).
  - When the **owner** records or confirms a return (`owner_return`, `owner_confirm`), you call `get_owned(db, user, record_id)`, which runs a plain `db.get(Record, rid)` **without `.with_for_update()`**!
  - In `add_return()`, you compute `reserved = sum(x.quantity for x in rec.returns if x.status in ('PENDING', 'CONFIRMED'))` in Python and check `if qty > rec.item.quantity - reserved:`.
  - Two concurrent requests (e.g., double-click or owner + borrower submitting simultaneously) will both read `reserved = 0` and commit two `ItemReturn` rows whose total returned quantity **exceeds the loan quantity**, corrupting `outstanding_quantity` into a negative number!
- **Order:**
  1. Lock the `Record` row with `SELECT ... FOR UPDATE` inside `add_return()` and `confirm_return()` (or `get_owned(..., for_update=True)`) before reading `rec.returns`.

---

## Priority 1: Backend Architecture, Latency & Data Integrity Bugs

### Mistake 6: Cold-Start Schema Reflection & Connection Churn on Every Page Load (`PT-004` / `PT-005`)
- **Where:** [`backend/main.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L23-L26), [`backend/migrate.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/migrate.py#L89-L100), [`backend/database.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/database.py#L53-L58), [`static/app.js`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/static/app.js#L418-L429)
- **What you did:**
  1. `vercel.json` already runs `python -m backend.migrate check` during build. Yet your FastAPI `lifespan` runs `ensure_database_current()` on **every serverless cold start**, opening a DB connection, querying `alembic_version`, and running `sa.inspect(connection).get_table_names(schema=schema)` against `pg_catalog` before the function can serve a single byte!
  2. On Vercel (`VERCEL == '1'`), you configured `NullPool` ([`backend/database.py:57`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/database.py#L57)). Every single `SessionLocal()` opens and closes a fresh TCP + TLS + PostgreSQL connection to Supavisor.
  3. Then in [`static/app.js:418-429`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/static/app.js#L418-L429), `init()` fires a **4-step sequential HTTP waterfall**:
     - `await api('/api/csrf')`
     - `await api('/api/auth/config')`
     - `await api('/api/me')`
     - `await Promise.all([api('/api/records'), api('/api/inbox')])`
     Every page load makes 5 separate API requests across 4 sequential round-trips, opening and tearing down multiple TLS connections to Supabase!
  4. On top of that, `email_delivery.py` (`httpx.post`) and `supabase_auth.py` (`with httpx.Client(...) as client:`) instantiate and destroy a brand-new `httpx.Client` (and TLS handshake) on every single call instead of reusing a module-level `httpx.Client`.
  5. And in `verify_code` ([`supabase_auth.py:288-292`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/supabase_auth.py#L288-L292)) and `refresh` ([`supabase_auth.py:304-308`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/supabase_auth.py#L304-L308)), after calling Supabase `/verify` or `/token` (which *already* returns the verified user object and signed JWT), you make a **second synchronous HTTP call** to `GET /auth/v1/user` (`verified_identity(access)`), doubling auth/refresh latency!
- **Order:**
  1. Skip `ensure_database_current()` on Vercel runtime startup (keep it in the build command and `GET /api/health` if needed).
  2. Combine `/api/csrf`, `/api/auth/config`, and `/api/me` into a single `/api/bootstrap` (or `/api/session`) endpoint so page initialization takes 1 request instead of 3 sequential requests.
  3. Reuse a persistent `httpx.Client` for Supabase Auth and Resend API calls.
  4. Validate the JWT / `user` payload returned directly by `/verify` and `/token` instead of making a redundant `GET /auth/v1/user` round-trip on every login and token refresh.

---

### Mistake 7: Three Different Email Validators and Unindexed `func.lower(email)` Full Table Scans
- **Where:** [`backend/email_delivery.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/email_delivery.py#L10-L14), [`backend/main.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L39-L44), [`backend/supabase_auth.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/supabase_auth.py#L231-L237), [`backend/main.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L213), [`backend/main.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L427), [`backend/supabase_auth.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/supabase_auth.py#L274)
- **What you did:**
  1. You wrote **three incompatible email validators** across three files:
     - `email_delivery.normalize_email`: uses `email_validator.validate_email()`.
     - `main.Credentials.normalize_email`: checks `'@' not in value or value.startswith('@') or value.endswith('@')` (accepts `a@@b` and `a @b`!).
     - `supabase_auth.EmailBody.email_address`: checks `value.count('@') != 1` (accepts `user@localhost` without a TLD, which `email_validator` rejects!).
  2. Every write path already normalizes emails with `.strip().casefold()`. Yet on read paths (`supabase_auth.py:274`, `main.py:213`, `main.py:427`), you query `where(func.lower(User.email) == email)` and `where(func.lower(Contact.email) == body.contact_email)`.
  3. In PostgreSQL, wrapping an indexed column in `lower(email)` **bypasses your B-tree index (`ix_users_email`) and forces a sequential table scan (`Seq Scan`)**! Meanwhile, in `provision_user` (`supabase_auth.py:156`) and `login` (`main.py:394`), you query `User.email == email` *without* `func.lower()`.
- **Order:**
  1. Use **one** shared email normalization function (`email_delivery.normalize_email`) across all Pydantic models (`Credentials`, `EmailBody`, `InviteEmail`, `RecordCreate`).
  2. Enforce lowercase storage everywhere (and optionally add a DB `CheckConstraint('email = lower(email)')`), then query `User.email == email` directly so PostgreSQL actually uses `ix_users_email`.
  3. Add an index on `(owner_id, email)` in `contacts`.

---

### Mistake 8: Sharing an `OFF` Record Never Updates `Contact.email`, Causing Duplicate Contacts
- **Where:** [`backend/main.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L210-L235), [`backend/main.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L427-L433), [`backend/main.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L476-L484)
- **What you did:**
  - When a user creates an `OFF` record for `"Rahul"` (without an email), `create_record` creates `Contact(name='Rahul', email=None)`.
  - When the user later clicks **"Move to On the Record"** (`POST /api/records/{id}/share` with `rahul@example.com`), `deliver_record` saves `recipient_email` on `Invitation`, **but leaves `rec.contact.email` as `None`**!
  - Not only does `GET /api/records` continue returning `contact_email: null` for that shared record, but the next time the owner creates an `ON` record for `rahul@example.com`, `create_record` fails to match the existing contact and creates a duplicate `"Rahul"` row in `contacts`.
- **Order:**
  1. When sharing a record whose contact has `email is None`, update `rec.contact.email = email` (or merge with the owner's existing contact for that email).

---

### Mistake 9: Schema & ORM Sloppiness in `backend/models.py`
- **Where:** [`backend/models.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/models.py#L42-L127)
- **What you did:**
  1. Look at lines 58–59 of [`backend/models.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/models.py#L58-L59):
     ```python
     loan_date: Mapped[datetime] = mapped_column(Date, nullable=False)
     due_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
     ```
     SQLAlchemy `Date` columns map to Python `datetime.date`, NOT `datetime.datetime`. You even imported `date` on line 3 and used it on `AppInvitation.invite_day`, but annotated `loan_date` and `due_date` as `Mapped[datetime]`!
  2. You put `ondelete='CASCADE'` on `LoginSession`, `AuthIdentity`, and `ItemLoan`, and then **forgot `ondelete` on every other foreign key** (`Contact.owner_id`, `Record.owner_id`, `Record.contact_id`, `Invitation.record_id`, `Invitation.recipient_user_id`, `AppInvitation.sender_id`, `ItemReturn.record_id`, `RecordEvent.record_id`). That is why deleting a user or a record fails with a foreign key constraint violation!
  3. `Record.contact_id` (`ForeignKey('contacts.id')`) has no index (`index=True` is missing).
  4. Every state machine column (`direction`, `mode`, `acknowledgment`, `state`, `delivery`, `status`, `proposed_by`, `actor`) is an unconstrained `String` with zero `CheckConstraint`s or `StrEnum` types.
- **Order:**
  1. Fix the `Mapped[date]` / `Mapped[date | None]` type annotations on `Record`.
  2. Define explicit `StrEnum`s for all domain states (`Direction`, `RecordMode`, `AcknowledgmentState`, `InvitationState`, `ReturnStatus`, `Actor`) and use them across `models.py` and `main.py`.
  3. Add a migration to index `records.contact_id` and configure explicit `ondelete` behaviors on foreign keys.

---

## Priority 2: Frontend Code Quality & UX Bugs (`static/app.js` & `static/style.css`)

### Mistake 10: Dead Error Handling in `showSignupShare()` That Destroys the Modal Before the User Can Read the Error
- **Where:** [`static/app.js`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/static/app.js#L373)
- **What you did:**
  Look closely at your `catch` block in `showSignupShare()` on line 373:
  ```javascript
  catch(err){$('#app-invite-error',el).textContent=err.message;el.remove();await showSignupShare();toast(err.message)}
  ```
  Read that out loud:
  1. You set `$('#app-invite-error', el).textContent = err.message` inside the modal `el`.
  2. **On the very next statement (`el.remove()`), you destroy the modal from the DOM** so the user never sees `#app-invite-error`!
  3. Then you call `await showSignupShare()`, which makes a network call to `GET /api/app-invites` and opens a brand-new modal—**wiping out the email address the user just typed**!
- **Order:**
  1. If the error is a validation error (`422` / `409`), keep the modal open, keep the user's input intact, and display `err.message` in `#app-invite-error`. Only refresh the quota list if a slot state actually changed (`503`).

---

### Mistake 11: Hand-Minified Code and Appended Override Stylesheets
- **Where:** [`static/app.js`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/static/app.js#L1-L429), [`static/style.css`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/static/style.css#L1-L164)
- **What you did:**
  - "Zero build step" does **not** mean "manually minify your source files into 2,500-character single lines so nobody can read or review git diffs."
  - In [`static/style.css`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/static/style.css#L1-L16), lines 1–16 are giant single-line CSS blobs (line 8 is **2,595 characters long**; line 9 is **2,286 characters long**).
  - Then, when you had to fix mobile layout bugs later, **you didn't edit lines 1–16**. Instead, you appended lines 18–164 at the bottom of `static/style.css` to override your own rules from lines 1–16!
    - `.modal` is defined on line 9 (`padding:33px 34px;max-height:92vh;overflow:auto`), then overridden on line 23 (`padding:0;max-height:100%;overflow:hidden`).
    - `.close-modal` is `position:absolute` on line 9, then overridden with `position:static` on line 25.
    - `@media(max-width:900px)` appears on line 14 **and again** on line 53.
    - `@media(max-width:600px)` appears on line 15 **and again** on line 91.
  - In [`static/app.js`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/static/app.js#L324-L415), lines 336, 350, 367, 372, 381, 403, and 405 are 500–925 character one-liners cramming HTML templates, event listeners, `fetch` calls, and `try/catch/finally` blocks onto single lines.
- **Order:**
  1. Format `static/app.js` and `static/style.css` with standard indentation and line breaks (e.g., Prettier / Biome).
  2. Merge the duplicate selectors and duplicate `@media(max-width:900px)` / `@media(max-width:600px)` blocks in `static/style.css` so each component has a single source of truth.

---

### Mistake 12: 21 Mutable Global Variables, Dead State, and Full-DOM Destruction on Polling
- **Where:** [`static/app.js`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/static/app.js#L7-L14), [`static/app.js`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/static/app.js#L385-L395)
- **What you did:**
  1. You declared 21 mutable module-level globals on lines 7–14. Four of them—`activeRecord`, `newOpen`, `shareLink`, and `busy`—are **dead variables**: assigned values and **never read anywhere in the codebase**.
  2. Every mutation (`openNew`, `openEdit`, `requestAcknowledgment`, `openReturn`, `openInbox`) calls `await loadRecords()`, which re-fetches `/api/records` AND `/api/inbox`, destroys and rebuilds the entire `#app` DOM via `innerHTML`, and then immediately makes a *third* API call (`openDetails(id)` or `openInbox(id)`) to re-open the modal!
  3. Your 30-second interval (`setInterval` on line 393) runs unconditionally even on the unauthenticated screen or guest share page. Worse, if the user is viewing the `INBOX` tab (`tab === 'INBOX'`), `refreshInbox()` calls `inboxDashboard()` -> `topLayout()`, which **wipes `$('#app').innerHTML` every 30 seconds**, destroying keyboard focus and scroll position while the user is reading their inbox!
  4. When a user signs up on `/signup` via local password (`authScreen`, line 175) or OTP (`supabaseAuthScreen`, line 206), you never `history.replaceState(null, '', '/')` after login succeeds—leaving the authenticated dashboard sitting at the URL `/signup`.
- **Order:**
  1. Delete the dead globals (`activeRecord`, `newOpen`, `shareLink`, `busy`) and encapsulate state in a single `state` object.
  2. In `refreshInbox()`, update only the `.record-list` container inside `inboxDashboard` instead of calling `topLayout()` and wiping the entire page shell.
  3. Call `history.replaceState(null, '', '/')` when transitioning from `/signup` to the authenticated dashboard.

---

## Priority 3: Python Hygiene & Maintainability Mistakes

### Mistake 13: Inline `__import__('os')` Hacks and Uncached Disk/Markdown Parsing
- **Where:** [`backend/main.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L299), [`backend/main.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py#L376), [`backend/policies.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/policies.py#L17-L40)
- **What you did:**
  1. In `backend/main.py` (lines 299 and 376), instead of putting `import os` at the top of the file like a normal Python developer, you wrote:
     ```python
     secure=(__import__('os').getenv('UDHAAR_COOKIE_SECURE') == 'true')
     ```
     Twice! Never use `__import__('os')` inline in production application code.
  2. In [`backend/policies.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/policies.py#L17-L40), `policy_page(name)` instantiates `MarkdownIt`, reads `PRIVACY.md` / `TERMS.md` / `RIGHTS.md` from disk, parses the Markdown AST, rewrites links, and builds the HTML string **on every single HTTP request**—for static files that never change at runtime!
  3. In [`backend/main.py`](file:///c:/Users/gopik/Documents/personal-projects/udhaar_mvp/backend/main.py), all 572 lines of schemas, auth helpers, CSRF dependencies, database serialization, and 22 route handlers are dumped into one monolithic file.
- **Order:**
  1. Replace `__import__('os')` with a top-level `import os` and a helper `cookie_secure() -> bool`.
  2. Decorate `policy_page(name)` in `backend/policies.py` with `@lru_cache(maxsize=8)` so static Markdown files are parsed once per process instead of on every request.
  3. Split `backend/main.py` into logical modules (`schemas.py`, `deps.py`, `routes/records.py`, `routes/inbox.py`, `routes/invites.py`) as you touch those areas.

---

## Summary Checklist for the Junior Engineer

| Order | Priority | ID | Mistake | Target Files | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | **P0** | M-01 | `Cache-Control: no-store` on `/static/*` + 2.65 MB unoptimized/duplicate PNGs | `backend/main.py`, `static/branding/*`, `logo/*` | **Fixed** |
| 2 | **P0** | M-02 | $1 + 3N$ and $1 + 6M$ N+1 SQL queries + lazy-loading `events` just to `.pop()` them | `backend/main.py`, `backend/models.py` | **Fixed** |
| 3 | **P0** | M-03 | Holding DB transaction & `FOR UPDATE` row lock across 15s Resend HTTP call | `backend/main.py`, `backend/email_delivery.py` | **Fixed** |
| 4 | **P0** | M-04 | Broken IP rate limiter locking out all users behind proxy (`request.client.host`) | `backend/supabase_auth.py` | **Fixed** |
| 5 | **P0** | M-05 | Missing `FOR UPDATE` lock in `owner_return` / `add_return` allowing over-returns | `backend/main.py` | **Fixed** |
| 6 | **P1** | M-06 | Cold-start DB reflection, 4-step frontend init waterfall, per-call `httpx.Client`, double `/user` call | `backend/main.py`, `backend/supabase_auth.py`, `static/app.js` | **Fixed** |
| 7 | **P1** | M-07 | 3 conflicting email validators + `func.lower(email)` bypassing B-tree index | `backend/main.py`, `backend/supabase_auth.py`, `backend/email_delivery.py` | **Fixed** |
| 8 | **P1** | M-08 | Sharing an `OFF` record leaves `Contact.email` as `None` and duplicates contacts | `backend/main.py` | **Fixed** |
| 9 | **P1** | M-09 | Wrong `Mapped[datetime]` types on `Date` columns & missing domain `StrEnum`s | `backend/models.py` | **Fixed** |
| 10 | **P2** | M-10 | `showSignupShare()` sets error text then immediately calls `el.remove()` | `static/app.js` | **Fixed** |
| 11 | **P2** | M-11 | Hand-minified 2,500-char lines in `app.js` & `style.css` + duplicate override CSS | `static/app.js`, `static/style.css` | **Fixed** |
| 12 | **P2** | M-12 | Dead global variables, full-DOM wipe on 30s inbox poll, stuck `/signup` URL | `static/app.js` | **Fixed** |
| 13 | **P3** | M-13 | Inline `__import__('os')` hacks & uncached per-request Markdown parsing | `backend/main.py`, `backend/policies.py` | **Fixed** |
