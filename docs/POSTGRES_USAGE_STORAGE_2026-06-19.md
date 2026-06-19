# PostgreSQL usage storage foundation

Date: 2026-06-19

## What changed

- Added `USAGE_STORAGE_BACKEND=local|postgres`.
- Added a PostgreSQL-backed `usage_events` table.
- Kept local `_usage/usage_*.json` storage as the default for development and tests.
- Exposed usage storage metadata in `/diagnostics`, `/providers`, and `/admin/overview`.
- Added `scripts/migrate_usage_json_to_postgres.py`.

## Why this matters

Usage, quota, and estimated-cost tracking must be shared across API and worker processes in production. PostgreSQL mode makes usage summaries durable and consistent across restarts and horizontally scaled API containers.

## Production setup

```env
DATABASE_URL=postgresql://user:password@host:5432/dbname
USAGE_STORAGE_BACKEND=postgres
DATABASE_AUTO_MIGRATE=true
```

## Migration

Preview:

```powershell
python scripts\migrate_usage_json_to_postgres.py --dry-run
```

Run:

```powershell
python scripts\migrate_usage_json_to_postgres.py
```

The migration preserves event ids, actor ids, resource references, units, estimated cost, metadata, and timestamps.

## Current limits

- Costs are still estimated internal counters, not Stripe metered billing records.
- There is no warehouse/export integration yet.
- There are no per-period rollup tables yet.
