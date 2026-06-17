# Code Audit - 2026-06-16

Project: `ЮТУБ АИ ЛОНГ` / `AI Video Studio MVP v0.4`

Repository: `https://github.com/milliardwb-sys/YOUTUBE-AI-LONG`

Scope: local repository code, backend API, mobile MVP, Docker/CI/dependency configuration, docs, and the attached audit ТЗ PDF `TZ_kompleksny_audit_mnogopolzovatelskoy_platformy.pdf`.

## 1. Executive Summary

Remediation update 2026-06-17:

- Backend runtime and dev dependencies were split into `requirements.txt` and `requirements-dev.txt`.
- FastAPI/Starlette/Pydantic/Uvicorn/OpenAI runtime dependencies were updated.
- `python-multipart` and `pytest` were removed from the production runtime dependency set.
- `pip-audit` was added to CI for backend runtime dependencies.
- Current backend runtime audit result: `No known vulnerabilities found`.
- Production API key placeholder/length validation, FFmpeg render timeout, and safer export packaging were added after this audit.

The project is a working technical MVP, not a production multi-user SaaS platform yet.

It can create a video-generation project, generate a script, collect safe visual sources, generate slides, create placeholder or OpenAI TTS audio, render MP4 through FFmpeg, package YouTube metadata, expose job progress, support cancel/retry, and report project readiness through `/stats` and `/projects/{id}/manifest`.

The strongest parts are:

- clear FastAPI surface;
- Pydantic validation for project payloads;
- safe local file path checks;
- SSRF-oriented source URL checks;
- API key gate for non-local environments;
- rate limiting;
- job history/events;
- Docker and CI scaffold;
- 28 passing backend tests;
- mobile TypeScript check passing.

The main blockers for production are:

- no users, sessions, roles, organizations, tenants, ownership checks, or RBAC;
- no database, migrations, row-level ownership model, or transactional storage;
- local JSON storage and local `ThreadPoolExecutor` jobs are not durable production infrastructure;
- dependency audit reports runtime vulnerabilities in backend dependency chain;
- mobile `EXPO_PUBLIC_API_KEY` is only a public client-side secret and cannot be used as real authorization;
- no audit log, admin panel, monitoring, backup/restore process, billing, webhook model, or legal consent flow;
- no real avatar provider, no voice consent storage, and no production render stack.

Production readiness estimate:

- Local MVP/demo: 75-80%.
- Private internal prototype: 45-55%.
- Public multi-user platform: 20-30%.
- Production SaaS with payments, roles, and user data: not ready.

## 2. Evidence Collected

Commands executed:

```bash
python -m pytest
npm.cmd run check:ci
python -m pip_audit -r backend/requirements.txt
npm.cmd audit --omit=dev --audit-level=moderate
docker compose config
rg secret/API/token patterns
rg dangerous APIs and TODO/placeholder markers
```

Results:

- Backend tests: `28 passed`.
- Mobile CI check: passed `npm audit --omit=dev --audit-level=high` and `tsc --noEmit`.
- Mobile strict audit: fails on moderate `js-yaml` chain through React Native/Metro/Jest.
- Backend dependency audit: 15 known vulnerabilities in 3 packages.
- Docker Compose config: valid.
- Git status: clean, `main` synced with `origin/main`.
- Secrets scan: no real hardcoded OpenAI/API keys found; only env names, examples, and documentation placeholders.

## 3. Architecture Map

Backend:

- `backend/app/main.py` - FastAPI app, middleware, routes, auth/rate limit, file serving, stats, manifest.
- `backend/app/models.py` - Pydantic models and enums.
- `backend/app/storage.py` - local file-backed project storage.
- `backend/app/pipeline.py` - guarded pipeline orchestration.
- `backend/app/services/*` - script, sources, screenshots, visuals, voice, avatar placeholder, render, jobs.
- `backend/app/utils/*` - file I/O, text utilities, identifier/path/URL security helpers.

Mobile:

- `mobile/App.tsx` - Expo MVP UI.
- `mobile/src/api.ts` - API client.
- `mobile/src/types.ts` - TypeScript DTOs.

Infrastructure:

- `backend/Dockerfile` - production-like backend image with non-root user and FFmpeg.
- `docker-compose.yml` - backend service and project volume.
- `.github/workflows/ci.yml` - backend tests, mobile check, docker build.

## 4. What Is Implemented

Backend API:

- Health/readiness/providers/diagnostics endpoints.
- Project CRUD.
- Project duplication.
- Sync pipeline endpoints.
- Queued job endpoints.
- Cancel/retry job controls.
- Job event history.
- Scene patch/insert/delete/reorder/regenerate-slide endpoints.
- File serving under controlled `DATA_DIR`.
- Project status/result endpoints.
- `/stats`.
- `/projects/{id}/manifest`.
- Maintenance cleanup.

Generation:

- Template script generator.
- Optional OpenAI LLM scene generator.
- Safe fallback from OpenAI to template.
- User URLs plus curated official sources.
- Optional Playwright screenshots.
- Offline fallback source cards.
- Pillow slide generation.
- Placeholder WAV generator.
- Optional OpenAI TTS.
- SRT and VTT generation.
- FFmpeg MP4 render.
- Thumbnail PNG.
- YouTube metadata.
- Quality report.
- Export ZIP package.

Safety:

- API key middleware.
- Production environment blocks private routes when API key is absent.
- Basic in-memory rate limiting.
- Project/job/scene/source identifier regex validation.
- Path traversal guard through `ensure_within_directory`.
- Source URL scheme/private/loopback/local checks.
- YouTube third-party video source guardrail.
- Tests for path traversal and private source URL rejection.

Developer experience:

- README and docs.
- Docker/Compose scaffold.
- GitHub Actions CI.
- Test suite.

## 5. What Is Not Implemented

Multi-user platform requirements from the PDF are mostly not implemented yet:

- user accounts;
- login/logout/session management;
- password reset;
- email/phone verification;
- organizations/teams;
- roles and permissions;
- owner/manager/moderator/admin/support/super-admin logic;
- tenant isolation;
- ownership checks;
- private user resources;
- payment/subscription model;
- billing limits;
- webhooks;
- admin panel;
- moderation workflow;
- support workflow;
- audit log;
- analytics events and funnels;
- SEO/public site layer;
- legal consent capture;
- data export/deletion;
- backup and restore;
- monitoring and alerting;
- incident response;
- production queue;
- production database;
- object storage and signed URLs.

## 6. Findings

### P1 - Backend runtime dependencies have known vulnerabilities

Evidence:

- `backend/requirements.txt:1-8`
- `pip-audit` result: 15 known vulnerabilities in `python-multipart==0.0.20`, `starlette==0.41.3`, `pytest==8.3.4`.

Impact:

- `starlette` is runtime through FastAPI.
- `python-multipart` is installed in runtime image even though current API does not expose upload endpoints.
- `pytest` is dev/test, but it is pinned in the same `requirements.txt` used by Docker image, so test-only dependencies enter production.

Risk:

- Public deployment inherits known CVEs.
- Production image contains unnecessary test dependency surface.

Recommendation:

- Split dependencies into `requirements.txt` and `requirements-dev.txt`.
- Remove `python-multipart` unless file upload endpoints are introduced.
- Upgrade FastAPI/Starlette chain after compatibility check.
- Keep `pytest` out of production image.
- Add CI dependency audit as a blocking job.

Acceptance:

- `python -m pip_audit -r backend/requirements.txt` returns no runtime vulnerabilities.
- Docker image does not include pytest.

### P1 - No real multi-user auth, RBAC, tenant isolation, or ownership checks

Evidence:

- `backend/app/models.py:100-116` project creation has no `user_id`, `owner_id`, `organization_id`, or tenant fields.
- `backend/app/models.py:253-278` project model has no ownership fields.
- `backend/app/storage.py:50-72` creates projects globally in `DATA_DIR`.
- `backend/app/main.py:79-97` uses one global API key, not per-user auth.

Impact:

- The platform cannot safely separate users, teams, projects, files, billing, or admin operations.
- PDF acceptance criteria around role matrix, direct ID substitution, backend/API ownership checks, and tenant isolation cannot be satisfied.

Risk:

- In a public multi-user deployment, anyone with the global API key can access all projects by ID.
- API key leakage would expose the entire instance.

Recommendation:

- Add proper authentication: users, sessions/JWT, refresh flow.
- Add `owner_id`/`organization_id` to all private resources.
- Implement policy guards per endpoint.
- Add tests for forbidden access to another user's project/job/file.
- Design RBAC/ABAC matrix before expanding API.

Acceptance:

- Every private endpoint receives authenticated principal context.
- Direct replacement of `project_id`, `job_id`, and file paths is covered by negative tests.

### P1 - Mobile API key is public and cannot be treated as a secret

Evidence:

- `mobile/src/api.ts:7-8`
- `mobile/src/api.ts:33-36`
- README documents `EXPO_PUBLIC_API_KEY`.

Impact:

- Expo public env values are bundled into the client app.
- This can protect a local demo from accidental calls, but it is not authentication for public users.

Risk:

- If used as production authorization, the API key can be extracted and reused.

Recommendation:

- Use real user authentication for mobile.
- Use API key only as a server-side integration secret or local demo gate.
- For public mobile, enforce user tokens and ownership on backend.

Acceptance:

- No production private endpoint trusts `EXPO_PUBLIC_API_KEY` as the only authorization.

### P1 - File-backed storage and local job runner are not production-safe

Evidence:

- `backend/app/services/job_service.py:37-42` explicitly states production should replace this queue.
- `backend/app/services/job_service.py:145-162` uses local process executor.
- `backend/app/storage.py:224-238` reads/writes project JSON files directly.

Impact:

- No cross-process locking.
- No transaction boundaries.
- No recovery from process crash mid-job.
- No queue visibility across replicas.
- No durable retries or worker isolation.

Risk:

- Data corruption or lost state under concurrent writes.
- Jobs disappear or stall on container restart.
- Horizontal scaling is unsafe.

Recommendation:

- Move projects/jobs to PostgreSQL.
- Use Redis/RQ, Celery, BullMQ, or Temporal for durable jobs.
- Make every pipeline step idempotent.
- Store artifacts in S3/R2 with signed URLs.

Acceptance:

- Multiple API replicas can safely process projects.
- Job state survives restart.
- Duplicate job execution is prevented by DB/queue constraints.

### P1 - Placeholder production API key may be accidentally deployed

Evidence:

- `backend/.env.production.example:26-28`
- `docker-compose.yml:6-7`
- `docker compose config` loads `API_KEY=CHANGE_ME_TO_A_LONG_RANDOM_SECRET` when example file is copied.

Impact:

- The docs say to replace the value, but Compose will run with the placeholder if copied blindly.

Risk:

- Public backend can be protected by a known placeholder secret.

Recommendation:

- Add startup validation: reject `API_KEY` values like `CHANGE_ME`, too short values, or known examples when `APP_ENV=production`.
- Add test for production placeholder rejection.

Acceptance:

- Container fails fast if production API key is weak or default.

### P2 - In-memory rate limiting is useful but not distributed

Evidence:

- `backend/app/main.py:131-150`

Impact:

- Works only per process.
- Does not protect a multi-replica deployment.
- Does not distinguish sensitive endpoint classes.

Risk:

- Brute force or spam protection becomes inconsistent in production.

Recommendation:

- Keep current limiter for MVP.
- Add API gateway/reverse proxy or Redis-backed limiter for production.
- Configure stricter limits for login/reset/search/upload once those endpoints exist.

Acceptance:

- Rate limits are shared across replicas and observable.

### P2 - File serving is path-safe but not authorization-aware

Evidence:

- `backend/app/main.py:578-586`
- `backend/app/utils/security.py:53-60`

What is good:

- Path traversal is blocked.
- Tests cover traversal attempt.
- API-key middleware protects the route when API key is configured.

Gap:

- There is no per-project or per-user authorization.
- A user with global API key can request any artifact path under `DATA_DIR`.

Recommendation:

- Replace `/files/{path}` with project-scoped artifact endpoints.
- Check authenticated principal ownership before serving files.
- For object storage, use short-lived signed URLs.

Acceptance:

- User A cannot fetch User B's file, even with a guessed path.

### P2 - Screenshot capture has partial SSRF protection but should be hardened before network use

Evidence:

- `backend/app/services/screenshot_service.py:61-64`
- `backend/app/utils/security.py:63-78`

What is good:

- URL is validated before and after navigation.
- DNS resolution check is enabled when browser screenshots are enabled.
- Plain HTTP and private hosts are blocked by default.

Gaps:

- Browser still performs network navigation and may follow redirects before final validation.
- No explicit allowlist/domain policy.
- No egress network sandbox.
- No content-size or time budget beyond navigation timeout.

Recommendation:

- Run browser screenshot workers in isolated network sandbox.
- Add allowlist or reputation policy for production.
- Enforce DNS/IP checks before every request if possible through browser routing.
- Add tests for redirect-to-private-host behavior.

Acceptance:

- Redirects to private IPs are blocked and covered by tests.

### P2 - Render subprocess has no timeout and can hang

Evidence:

- `backend/app/services/render_service.py:178-186`

Impact:

- FFmpeg can hang on malformed media, bad filter, or resource exhaustion.

Risk:

- Worker slot can be held indefinitely.

Recommendation:

- Add configurable render timeout.
- Kill process on timeout.
- Persist timeout as job failure with structured error.

Acceptance:

- Test covers timeout path with mocked subprocess.

### P2 - ZIP packaging trusts stored paths too much

Evidence:

- `backend/app/services/render_service.py:235-250`

Context:

- Normal pipeline writes paths under project directory.
- API currently does not allow direct result path mutation.

Risk:

- If stored JSON is corrupted or manually modified, ZIP can include files outside the project directory.

Recommendation:

- Before adding any artifact to ZIP, enforce `ensure_within_directory(project_dir, file_path)`.
- Add test with tampered path.

Acceptance:

- ZIP never includes files outside project directory.

### P2 - Observability is minimal

Evidence:

- `backend/app/main.py:108-119` adds request log fields and `x-request-id`.
- `/health`, `/ready`, `/diagnostics`, `/stats`, `/manifest` exist.

Gaps:

- No metrics endpoint.
- No tracing.
- No error tracking.
- No alerting.
- No structured job duration metrics.
- No dashboard or SLOs.

Recommendation:

- Add Prometheus/OpenTelemetry or hosted APM.
- Record job duration, failures by step, queue depth, render time, artifact size.
- Add synthetic checks for create-project and generate-script.

Acceptance:

- Team can detect failed job spike before users report it.

### P2 - CI is useful but not complete for production release

Evidence:

- `.github/workflows/ci.yml` runs backend tests, mobile checks, docker config/build.

Gaps:

- No backend dependency audit gate.
- No secrets scan.
- No lint/format check.
- No coverage reporting.
- No Docker vulnerability scan.
- No deployment workflow/rollback.

Recommendation:

- Add `pip-audit`, `npm audit --audit-level=moderate`, secret scan, Ruff/Black or equivalent, Docker scan.
- Keep `audit:prod` high-level for CI if strict React Native chain cannot be resolved immediately, but track moderate vulnerabilities separately.

Acceptance:

- CI blocks new high/critical vulnerabilities and flags moderate backlog.

### P3 - Documentation has good coverage but mixed encoding artifacts exist in some terminal views

Evidence:

- Several strings appear as mojibake in terminal output, while some files render normal Russian text.

Impact:

- Editing/searching Russian docs from Windows terminal can be confusing.

Recommendation:

- Normalize all docs and source comments to UTF-8.
- Add `.editorconfig`.

Acceptance:

- `python -c "Path(...).read_text(encoding='utf-8')"` and common editors show Russian correctly.

## 7. Security Checklist Against PDF

Covered:

- Runtime validation: yes, through Pydantic.
- Path traversal: yes, tested.
- Basic API auth gate: yes.
- Basic rate limit: yes.
- SSRF guard for source URLs: partial but thoughtful.
- Secrets in repo: no real secrets found.
- CORS configurable: yes.

Not covered:

- User auth.
- Sessions.
- RBAC.
- Admin roles.
- Tenant isolation.
- Ownership checks.
- IDOR between users.
- CSRF/cookie strategy.
- Webhook signatures.
- Payments.
- Audit log.
- Data export/deletion.
- Legal consent.
- Production monitoring.
- Backup/restore.

## 8. Product/UX Audit Snapshot

Mobile MVP is enough for demo:

- enter topic;
- choose official sources/LLM/TTS/subtitles toggles;
- start job;
- poll progress;
- cancel/retry;
- inspect links and manifest.

Not enough for production:

- no authentication flow;
- no onboarding;
- no project list/search;
- no scene editor UI;
- no source editor UI;
- no final preview player;
- no upload/publish workflow;
- no error recovery guide;
- no billing/limits UX;
- no admin/support UI.

## 9. API Audit Snapshot

Good:

- API routes are clear and testable.
- Project lifecycle is explicit.
- Job endpoints are separated from sync generation.
- Manifest endpoint improves auditability.

Gaps:

- No OpenAPI examples per endpoint beyond docs.
- No pagination for project/job lists.
- No idempotency keys for generation requests.
- No structured error schema across all errors.
- No request body size limits visible in app config.
- No per-route rate limit classes.

## 10. Data Model Audit

Good for MVP:

- compact Pydantic models;
- clear project/job/scene/source/result concepts;
- timestamps and statuses exist.

Not production:

- no relational schema;
- no migrations;
- no constraints;
- no foreign key ownership;
- no query indexes;
- no data retention model beyond cleanup days;
- no personal data inventory;
- no consent/audit entities.

## 11. Roadmap

### 2-4 weeks

1. Split runtime/dev dependencies and fix backend dependency vulnerabilities.
2. Reject weak/default production API keys on startup.
3. Add render subprocess timeout.
4. Enforce project-dir checks before ZIP packaging.
5. Add project-scoped file endpoint or ownership-ready artifact abstraction.
6. Add dependency/secrets scan to CI.
7. Add tests for DNS redirect/private-host screenshot cases.
8. Normalize UTF-8/editor config.

### 1-3 months

1. Add users/auth/session model.
2. Add PostgreSQL schema and migrations.
3. Add owner/org fields to projects/jobs/files.
4. Add RBAC/ABAC policy layer.
5. Replace local ThreadPoolExecutor with durable queue.
6. Move artifacts to object storage.
7. Add metrics/tracing/error tracking.
8. Build real project list and scene/source editor UI.

### 3-6 months

1. Add billing/limits/cost tracking.
2. Add admin/support/moderation workflows and audit log.
3. Add legal consent, data export/delete, retention controls.
4. Add production render stack and provider-specific cost/retry controls.
5. Add real avatar provider with consent workflow.
6. Add analytics events/funnels and dashboards.
7. Add backup/restore drills and incident response playbooks.

## 12. Final Readiness Matrix

| Area | Status | Notes |
| --- | --- | --- |
| Local backend MVP | Mostly ready | Tests pass; generation pipeline works. |
| Mobile MVP | Mostly ready | Typecheck passes; minimal UI only. |
| Docker backend | Partially ready | Build/config ready; dependency vulnerabilities remain. |
| CI | Partially ready | Tests/build present; scans missing. |
| Security baseline | Partial | API key, path checks, SSRF guard; no user/RBAC/tenant model. |
| Multi-user platform | Not ready | Core role/ownership model absent. |
| Payments/webhooks | Not implemented | Required by PDF for monetized platform. |
| Admin/support/moderation | Not implemented | Required by PDF. |
| Analytics/SEO | Not implemented | Required by PDF for growth audit. |
| Observability | Minimal | Health/ready/stats exist; no production monitoring. |
| Legal/privacy | Not implemented | Consent/export/delete/retention missing. |

## 13. Conclusion

The codebase is coherent and useful as an MVP foundation for AI video generation. It is not yet a multi-user platform in the sense required by the audit ТЗ. The highest priority is to close dependency risk, introduce real auth/ownership boundaries, and replace local storage/jobs with production-grade persistence and queueing.

The next engineering move should be a hardening sprint, not feature expansion: dependency cleanup, stronger production startup validation, render timeout, artifact path checks, CI scans, and an explicit auth/tenant design.
