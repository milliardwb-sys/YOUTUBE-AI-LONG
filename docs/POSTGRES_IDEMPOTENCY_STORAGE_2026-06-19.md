# PostgreSQL idempotency storage foundation

Date: 2026-06-19

## What changed

- Added `IDEMPOTENCY_STORAGE_BACKEND=local|postgres`.
- Added a PostgreSQL-backed `idempotency_records` table.
- Kept local `_idempotency/*.json` storage as the default for development and tests.
- Exposed idempotency storage metadata in `/diagnostics` and `/providers`.
- Added `scripts/migrate_idempotency_json_to_postgres.py`.

## Why this matters

Retry-safe POST endpoints only work reliably in multi-instance deployments when every API process shares the same idempotency records. PostgreSQL mode prevents duplicate resource creation across API restarts and horizontally scaled API containers.

## Production setup

```env
DATABASE_URL=postgresql://user:password@host:5432/dbname
IDEMPOTENCY_STORAGE_BACKEND=postgres
DATABASE_AUTO_MIGRATE=true
```

## Migration

Preview:

```powershell
python scripts\migrate_idempotency_json_to_postgres.py --dry-run
```

Run:

```powershell
python scripts\migrate_idempotency_json_to_postgres.py
```

## Current limits

- This stores idempotency records durably, but does not replace a full distributed lock service.
- Retention cleanup is still time-based and runs through the existing maintenance endpoint.
