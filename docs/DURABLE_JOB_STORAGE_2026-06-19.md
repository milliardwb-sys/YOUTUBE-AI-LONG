# Durable Job Storage Update - 2026-06-19

This update closes the first practical slice of the production backlog item "durable queue instead of local ThreadPoolExecutor".

## Implemented

- New job state storage switch:
  - `JOB_STORAGE_BACKEND=local`
  - `JOB_STORAGE_BACKEND=postgres`
- PostgreSQL job repository backed by a `jobs` table.
- Canonical job documents are stored as `jsonb` payloads.
- Frequently queried fields are duplicated into indexed columns:
  - `project_id`
  - `owner_id`
  - `organization_id`
  - `type`
  - `status`
  - `progress`
  - `current_step`
  - `created_at`
  - `updated_at`
  - `started_at`
  - `completed_at`
- PostgreSQL indexes for current API access patterns:
  - project job polling;
  - admin/status listing;
  - owner and organization filtering;
  - active queued/running jobs.
- Existing `JobStore` API remains stable for `JobRunner` and FastAPI handlers.
- `/ready`, `/diagnostics`, `/providers`, and job stats expose job storage metadata.
- `backend/.env.production.example` uses `JOB_STORAGE_BACKEND=postgres`.
- Migration helper:
  - `python scripts/migrate_jobs_json_to_postgres.py --dry-run`
  - `python scripts/migrate_jobs_json_to_postgres.py`

## How To Enable

Local JSON mode remains the default:

```text
JOB_STORAGE_BACKEND=local
```

PostgreSQL mode:

```text
JOB_STORAGE_BACKEND=postgres
DATABASE_URL=postgresql://user:password@host:5432/database
DATABASE_AUTO_MIGRATE=true
```

## Migration Flow

1. Keep `DATA_DIR` pointed at the directory that contains existing `_jobs/job_*.json` files.
2. Set `DATABASE_URL`.
3. Run a dry run:

```bash
python scripts/migrate_jobs_json_to_postgres.py --dry-run
```

4. Run migration:

```bash
python scripts/migrate_jobs_json_to_postgres.py
```

5. Start backend with:

```text
JOB_STORAGE_BACKEND=postgres
```

## Still Not Production-Complete

- Job execution still uses the in-process `ThreadPoolExecutor`.
- There is no separate worker process, leasing loop, retry backoff policy, or dead-letter queue yet.
- Jobs that were running during a process crash are durable as records, but they are not automatically resumed by a separate worker.
- There is no Redis/BullMQ/Celery/Temporal integration yet.
- There is no Alembic migration chain yet; schema bootstrap is automatic and intentionally minimal.
