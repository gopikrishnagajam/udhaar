# Udhaar

Udhaar is a personal and shared ledger for things people lend, borrow, owe, and
return. It helps people remember arrangements they have already made and keep
a history of what happened.

The product direction is similar to a shared expense ledger, extended to physical
items and paid lending without complex expense splitting. Users create records
for their own relationships. Item discovery, public listings, and payment
processing are outside the agreed scope.

**Public beta:** https://udhaar-mvp.vercel.app

**Maintainer:** [Gopi krishna Gajam](https://github.com/gopikrishnagajam)

**License:** [MIT](LICENSE)

## Current capabilities

- Track physical items lent or borrowed, including quantities, dates, and notes.
- Keep private **Off the Record** entries or request **On the Record** acknowledgment.
- Receive requests in app for existing accounts; use private emailed links for guests.
- Track handover acknowledgment separately from partial and completed returns.
- Let the lender confirm receipt of shared returns.
- View a record's activity history and invite friends.

Paid rentals, payment entries, earnings summaries, and general money balances
are **planned capabilities, not implemented features**. See
[Product direction](docs/product-direction.md) and [Roadmap](docs/roadmap.md).

## Development

Use Python 3.13 or Docker Desktop with Linux containers. A direct Python run
defaults to local SQLite and development password authentication:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m backend.migrate upgrade
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Open http://localhost:8000. These defaults assume hosted environment variables
are not set in your shell. Python does not automatically load `.env`.
Private local records work without email credentials.

[Development and testing](docs/development.md) covers Docker PostgreSQL, hosted
Supabase development, browser checks, and configuration. Hosted-data development
can share the public beta database; use isolated local data for routine work.

## Documentation

Start with the [documentation index](docs/README.md).

| Guide | Purpose |
| --- | --- |
| [Product direction](docs/product-direction.md) | Audience, scope, terminology, and record semantics |
| [Roadmap](docs/roadmap.md) | Priorities, decisions, and release gates |
| [Architecture](docs/architecture.md) | Components, implemented schema, and access boundaries |
| [Development](docs/development.md) | Setup, tests, and repository layout |
| [Operations](docs/operations.md) | Releases, backups, incidents, and data requests |
| [Legal considerations](docs/legal-considerations.md) | Research, product boundaries, and unresolved legal questions |

The workspace's `TODO.md` is the production-testing backlog. Read it before changes,
retain stable IDs, and distinguish local validation from public acceptance. It is
currently Git-ignored; shared product direction and priorities live in `docs/`.

## Policies and security

[Privacy](PRIVACY.md), [Terms](TERMS.md), [Rights](RIGHTS.md), and
[Security](SECURITY.md) describe the current beta. Policy documents also serve the
app's public pages and stay at the repository root for packaging.

Guest links grant access to their holder and do not independently verify identity.
Account export/deletion currently require manual assistance. The MIT license
covers source code and documentation, not private user data.
