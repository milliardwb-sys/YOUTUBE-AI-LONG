# PostgreSQL audit storage foundation

Date: 2026-06-19

## What changed

- Added `AUDIT_STORAGE_BACKEND=local|postgres`.
- Added a PostgreSQL-backed `audit_events` table for user, admin, organization, billing, consent, project, scene, and job audit events.
- Kept the existing local `_audit/audit_*.json` backend as the default for development and tests.
- Exposed audit storage metadata in `/diagnostics`, `/providers`, and `/admin/overview`.
- Added `scripts/migrate_audit_json_to_postgres.py` for moving local JSON audit events into PostgreSQL.

## Production setup

Set:

```env
DATABASE_URL=postgresql://user:password@host:5432/dbname
AUDIT_STORAGE_BACKEND=postgres
DATABASE_AUTO_MIGRATE=true
```

With `DATABASE_AUTO_MIGRATE=true`, the backend creates the `audit_events` table and query indexes on startup.

## Migration

Preview:

```powershell
python scripts\migrate_audit_json_to_postgres.py --dry-run
```

Run:

```powershell
python scripts\migrate_audit_json_to_postgres.py
```

The migration preserves audit event ids, timestamps, actions, actor ids, resource references, request ids, and metadata. Re-running the migration is idempotent because PostgreSQL inserts ignore existing event ids.

## Current limits

- This is durable database storage, not a tamper-proof immutable ledger.
- There is no cryptographic event chaining or WORM retention yet.
- Admin/export tooling can read events, but there is no dedicated audit analytics UI yet.
