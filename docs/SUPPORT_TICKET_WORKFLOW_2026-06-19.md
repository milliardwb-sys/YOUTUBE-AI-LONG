# Support ticket workflow foundation

Date: 2026-06-19

## What changed

- Added local JSON-backed support ticket storage under `_support/tickets`.
- Added support ticket models:
  - status: `open`, `pending`, `resolved`, `closed`;
  - priority: `low`, `normal`, `high`, `urgent`;
  - optional links to user, organization, project, and job;
  - operator assignment, tags, and notes.
- Added admin endpoints:
  - `GET /admin/support/tickets`
  - `POST /admin/support/tickets`
  - `GET /admin/support/tickets/{ticket_id}`
  - `PATCH /admin/support/tickets/{ticket_id}`
  - `POST /admin/support/tickets/{ticket_id}/notes`
- Added support ticket counts to `/admin/overview`.
- Added audit events for create, update, and note operations.

## Operator flow

1. Admin creates a ticket linked to the affected user/project/job.
2. Admin filters tickets by status, user, or project.
3. Admin updates status, priority, assignee, and tags.
4. Admin adds internal or public notes.
5. Audit log records every support mutation.

## Current limits

- Storage is local JSON only; PostgreSQL support ticket storage is still a follow-up.
- There is no public customer support form yet.
- There is no dedicated web admin UI yet.
- There is no SLA/escalation automation or notification provider yet.
