# PostgreSQL Project Storage Update - 2026-06-19

This update closes the first practical slice of the production backlog item "PostgreSQL instead of JSON files".

## Implemented

- New project metadata storage switch:
  - `PROJECT_STORAGE_BACKEND=local`
  - `PROJECT_STORAGE_BACKEND=postgres`
- New database settings:
  - `DATABASE_URL`
  - `DATABASE_CONNECT_TIMEOUT_SECONDS`
  - `DATABASE_AUTO_MIGRATE`
- PostgreSQL project repository backed by a `projects` table.
- Canonical project documents are stored as `jsonb` payloads.
- Frequently queried API fields are duplicated into indexed columns:
  - `owner_id`
  - `organization_id`
  - `status`
  - `current_step`
  - `topic`
  - `created_at`
  - `updated_at`
- PostgreSQL indexes for current API access patterns:
  - owner/project listing;
  - organization/project listing;
  - status filtering;
  - created-at sorting;
  - active project lookup.
- Existing `ProjectStore` API remains stable for the pipeline and FastAPI handlers.
- Local artifact paths still use `DATA_DIR/<project_id>/...`.
- `/ready`, `/diagnostics`, `/providers`, and `/stats` expose project storage metadata.
- Docker Compose now includes a PostgreSQL service and persistent DB volume.
- `backend/.env.production.example` is configured for the compose PostgreSQL service.
- Migration helper:
  - `python scripts/migrate_projects_json_to_postgres.py --dry-run`
  - `python scripts/migrate_projects_json_to_postgres.py`

## How To Enable

Local JSON mode remains the default:

```text
PROJECT_STORAGE_BACKEND=local
```

PostgreSQL mode:

```text
PROJECT_STORAGE_BACKEND=postgres
DATABASE_URL=postgresql://user:password@host:5432/database
DATABASE_AUTO_MIGRATE=true
```

In Docker Compose, update `backend/.env.production` from the example and replace the placeholder database password before public deployment.

## Migration Flow

1. Keep `DATA_DIR` pointed at the directory that contains existing `project_*/project.json` folders.
2. Set `DATABASE_URL`.
3. Run a dry run:

```bash
python scripts/migrate_projects_json_to_postgres.py --dry-run
```

4. Run migration:

```bash
python scripts/migrate_projects_json_to_postgres.py
```

5. Start backend with:

```text
PROJECT_STORAGE_BACKEND=postgres
```

## Still Not Production-Complete

- Users, sessions, organizations, consent records, audit events, usage events, idempotency records, and jobs are still file-backed.
- Jobs are still executed by local `ThreadPoolExecutor`; durable queue is a separate backlog item.
- Generated artifacts still live on local disk unless a future object-storage backend is enabled.
- There is no Alembic migration chain yet; schema bootstrap is automatic and intentionally minimal.
- There is no database connection pool package yet; operations open short-lived psycopg connections.
- Backup/restore still focuses on local files and does not dump/restore PostgreSQL.
