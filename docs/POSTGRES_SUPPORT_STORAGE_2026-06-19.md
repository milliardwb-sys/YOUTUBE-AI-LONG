# PostgreSQL support ticket storage foundation

Date: 2026-06-19

## What changed

- Added `SUPPORT_STORAGE_BACKEND=local|postgres`.
- Added a PostgreSQL-backed `support_tickets` table.
- Kept local `_support/tickets/ticket_*.json` storage as the default for development and tests.
- Preserved the existing admin support API surface.
- Added `scripts/migrate_support_json_to_postgres.py` for moving local support tickets into PostgreSQL.

## Production setup

Set:

```env
DATABASE_URL=postgresql://user:password@host:5432/dbname
SUPPORT_STORAGE_BACKEND=postgres
DATABASE_AUTO_MIGRATE=true
```

With `DATABASE_AUTO_MIGRATE=true`, the backend creates the `support_tickets` table and indexes for status, user, project, and job lookups.

## Migration

Preview:

```powershell
python scripts\migrate_support_json_to_postgres.py --dry-run
```

Run:

```powershell
python scripts\migrate_support_json_to_postgres.py
```

The migration preserves ticket ids, status, priority, links to user/project/job, tags, notes, timestamps, and resolution time.

## Current limits

- This adds durable storage for support tickets, not a full helpdesk UI.
- There is no SLA/escalation automation yet.
- Notifications to email/Slack/Telegram are still a follow-up.
