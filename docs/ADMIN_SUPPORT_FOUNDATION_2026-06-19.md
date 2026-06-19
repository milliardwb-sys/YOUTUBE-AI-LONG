# Admin/Support Foundation Update - 2026-06-19

This update closes the first practical slice of the production backlog item "admin/support panel".

## Implemented

- Admin route guard:
  - `ADMIN_API_KEY`
  - request header: `X-Admin-Key`
- In non-local environments, admin routes require `ADMIN_API_KEY`.
- If the public `API_KEY` is configured, admin routes still pass through the normal `X-API-Key` middleware first.
- Admin/support API endpoints:
  - `GET /admin/overview`
  - `GET /admin/users`
  - `GET /admin/projects`
  - `GET /admin/jobs`
  - `GET /admin/audit/events`
  - `GET /admin/usage`
- Admin overview includes:
  - user counts;
  - organization count;
  - project storage stats;
  - artifact storage metadata;
  - job stats;
  - usage summary;
  - audit event count.
- Admin project/user endpoints cross normal user boundaries, while regular user endpoints remain isolated.
- Pagination headers are returned on admin list endpoints.
- Backend service additions:
  - `AuthService.list_users`
  - `OrganizationService.list_all`
- Backend tests cover admin key gating and cross-user admin project/user listing.

## Verified

- Admin tests are included in the full backend suite.

## Still Not Production-Complete

- This is an admin API foundation, not a polished web admin UI.
- There is no support impersonation workflow.
- There is no fine-grained support role separate from `ADMIN_API_KEY`.
- There is no admin action audit for read-only support views yet.
- There is no moderation queue, refund/billing console, or incident dashboard.
- Admin API should be moved behind managed auth/OIDC and RBAC before public SaaS launch.
