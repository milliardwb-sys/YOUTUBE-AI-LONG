# Organizations/RBAC Foundation Update - 2026-06-18

This update closes the first practical slice of the production backlog item "organizations/roles/RBAC".

## Implemented

- File-backed organization storage in `backend/app/services/organization_service.py`.
- Organization and membership models:
  - `Organization`
  - `OrganizationMember`
  - `OrganizationRole`: `owner`, `admin`, `editor`, `viewer`
  - API request models for creating organizations and managing members.
- Personal organization creation during user registration.
- Project creation now supports `organization_id`.
- When user auth is enabled and no `organization_id` is sent, new projects are placed into the user's personal organization.
- Project listing now returns projects visible through ownership or organization membership.
- RBAC policy checks on project, job, scene, file, and audit-resource access:
  - `viewer`: read-only project/job/file/audit-resource access.
  - `editor`: read/write project access, scene edits, duplicate, generation/job start/cancel/retry.
  - `admin`: editor rights plus project delete and member management.
  - `owner`: admin rights plus owner membership changes.
- Organization API endpoints:
  - `GET /organizations`
  - `POST /organizations`
  - `GET /organizations/{organization_id}`
  - `GET /organizations/{organization_id}/members`
  - `POST /organizations/{organization_id}/members`
  - `PATCH /organizations/{organization_id}/members/{user_id}`
  - `DELETE /organizations/{organization_id}/members/{user_id}`
- Audit events for explicit organization and membership changes.
- Audit resource access now allows members to view events for a specific readable project/job/organization while keeping the unfiltered audit feed scoped to the current actor.
- Mobile TypeScript API wrappers and types for organizations and members.
- Backend tests for personal organization creation and role-based access control.

## Verified

- `python -m pytest backend\tests\test_pipeline.py -q --maxfail=1`
  - Result: `49 passed, 1 warning`
- `npm.cmd run check:ci`
  - Result: passed.
  - Note: npm still reports moderate `js-yaml` advisories through React Native/Metro/Jest, but the configured high-severity production audit passes.

## Still Not Production-Complete

- RBAC storage is still local JSON, not PostgreSQL.
- There is no managed auth/OIDC provider yet.
- There is no invite email flow, password reset, email verification, device/session management UI, or support/super-admin policy.
- There is no web admin/support panel for browsing organizations, users, projects, usage, and audit events.
- Billing plans/Stripe subscriptions are still not implemented.
- Durable queue, object storage, and production observability remain open production backlog items.
