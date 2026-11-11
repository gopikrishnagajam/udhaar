# Udhaar documentation

Udhaar is a personal and shared ledger for existing relationships. The current
beta tracks physical items; paid rental and earnings records are the next
feature under investigation.

## Product and planning

| Document | Use it to |
| --- | --- |
| [Product direction](product-direction.md) | Understand the audience, record model, scope, and terminology |
| [Roadmap](roadmap.md) | Distinguish current behavior, agreed direction, and open decisions |
| [Legal considerations](legal-considerations.md) | Review the external-payment scope and legal research |

## Engineering and operations

| Document | Use it to |
| --- | --- |
| [Development and testing](development.md) | Run the app, choose an environment, and validate changes |
| [Architecture and schema](architecture.md) | Trace components, ownership, records, and acknowledgments |
| [Authentication](authentication.md) | Configure email codes, sessions, cookies, and local auth |
| [Authentication and email limits](auth-rate-limits.md) | Diagnose browser, backend, provider, and invitation limits |
| [Database and migrations](database.md) | Choose connections, inspect schema, and apply upgrades |
| [Email invitations](email-invitations.md) | Configure delivery and understand recipient routing |
| [Vercel deployment](vercel-deployment.md) | Maintain the existing public beta |
| [Operations](operations.md) | Release, monitor, back up, restore, and handle private data requests |

## Documentation maintenance

Product scope belongs in the product direction; delivery priorities belong in
the roadmap. Technical guides describe implemented behavior. Pending features
must stay labeled as planned until implementation and acceptance are complete.

The local `TODO.md` holds production feedback, stable IDs, investigation evidence,
and retest status. It is not currently versioned. Keep the tracked roadmap useful
without relying on that local file. Historical deployments remain in the backlog;
the guides describe how to operate the current system.

Public policies remain at the root: [Privacy](../PRIVACY.md),
[Terms](../TERMS.md), [Rights](../RIGHTS.md), and [Security](../SECURITY.md).
