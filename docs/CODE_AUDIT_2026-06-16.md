# Code Audit - актуализация 2026-06-17

Проект: `ЮТУБ АИ ЛОНГ` / `AI Video Studio MVP v0.4`

Репозиторий: `https://github.com/milliardwb-sys/YOUTUBE-AI-LONG`

Цель аудита: зафиксировать фактическое состояние backend, mobile MVP, API, интеграций, инфраструктуры и готовности к превращению MVP в многопользовательскую платформу.

## 1. Краткий вывод

Проект уже является рабочим техническим MVP генератора длинных YouTube-видео:

- пользователь задает тему и настройки ролика;
- backend создает проект;
- pipeline генерирует сценарий, источники, визуалы, озвучку, субтитры, metadata и итоговый MP4;
- job-система позволяет запускать генерацию асинхронно, смотреть прогресс, отменять и повторять задачи;
- мобильный Expo-клиент умеет создавать проекты, авторизоваться, видеть список проектов, открывать старые проекты, редактировать сцены и управлять job;
- есть базовая auth/ownership foundation: регистрация, логин, bearer-сессии, logout, owner_id у проектов/job, изоляция чужих ресурсов;
- добавлены hardening-механизмы: API key gate, rate limit, body size limit, SSRF/path traversal checks, render timeout, dependency/secrets checks;
- добавлены pagination headers и Idempotency-Key для критичных POST endpoints;
- добавлен file-backed audit log для auth/project/job/scene действий с пользовательской изоляцией;
- добавлен MVP usage/limits/cost tracking слой и secure token persistence в мобильном клиенте через Expo SecureStore.

Это уже хорошая база для demo/MVP и внутреннего прототипа. До public SaaS еще далеко: нет PostgreSQL, durable queue, object storage, ролей, организаций, Stripe/subscriptions, production observability, managed auth/OIDC, полноценного web/admin UI и юридических consent/data flows.

## 2. Оценка готовности

| Уровень | Оценка | Комментарий |
| --- | ---: | --- |
| Local demo / технический MVP | 80-85% | Основной pipeline и мобильный MVP работают, тесты покрывают ключевые сценарии. |
| Внутренний прототип для ограниченной команды | 60-65% | Есть auth foundation и ownership, но storage/job все еще локальные. |
| Закрытая beta с несколькими пользователями | 45-55% | Нужны Postgres, durable queue, object storage, observability, backup. |
| Public multi-user SaaS | 35-45% | Нет production auth/RBAC, Stripe billing, admin, legal/privacy workflows; audit/usage пока локальные MVP. |
| Enterprise/marketplace platform | 20-30% | Нужны роли, организации, SLA, compliance, мониторинг, политики данных. |

## 3. Проверенные области

Проверены:

- FastAPI backend: routes, middleware, auth, project/job/file access.
- Pydantic models: project, scene, source, result, job, auth DTO.
- Local storage: JSON project store, job store, auth store, idempotency store, audit log store, usage ledger.
- Pipeline: script, source collection, visual slides, voice, avatar placeholder, render/export.
- Mobile Expo client: API client, auth flow, project list, project controls, scene editor.
- Security controls: API key, bearer token, owner checks, path validation, URL validation, rate limit.
- Docs: `README`, `API`, `ARCHITECTURE`, `PROJECT_OVERVIEW`, `NEXT_STEPS`.
- CI/dependencies: pytest, mobile TypeScript check, pip-audit, secret scan.

## 4. Что реализовано

### Backend API

Реализовано:

- `GET /health`, `GET /ready`, `GET /diagnostics`, `GET /providers`.
- `POST /auth/register`, `POST /auth/login`, `GET /auth/me`, `POST /auth/logout`.
- `POST /projects`, `GET /projects`, `GET /projects/{id}`, `PATCH /projects/{id}`, `DELETE /projects/{id}`.
- `POST /projects/{id}/duplicate`.
- sync pipeline endpoints: generate script, collect sources, generate slides, generate voice, prepare avatar, render, generate all.
- queued endpoints: `POST /projects/{id}/jobs/{job_type}`, `POST /projects/{id}/generate-all-queued`.
- job endpoints: get job, events, cancel, retry, project jobs.
- scene editor endpoints: patch, insert, delete, reorder, regenerate slide.
- file endpoint with path and owner checks.
- manifest/status/result endpoints.
- usage endpoint: `GET /usage/me`;
- cleanup endpoint для старых projects/jobs/sessions/idempotency/audit records.

### API contracts

Реализовано:

- единый `x-request-id` на ответах;
- structured error body: старое поле `detail` сохранено, добавлен объект `error`;
- request body size limit через `MAX_REQUEST_BODY_BYTES`;
- pagination для `GET /projects`, `GET /projects/{id}/jobs`, `GET /jobs/{job_id}/events`;
- headers `X-Total-Count`, `X-Limit`, `X-Offset`;
- `Idempotency-Key` для `POST /projects`, `POST /projects/{id}/duplicate`, `POST /projects/{id}/jobs/{job_type}`, `POST /projects/{id}/generate-all-queued`;
- replay header `X-Idempotent-Replay`;
- `409` при повторе того же idempotency key с другим payload.

### Auth и ownership

Реализовано:

- optional auth через `ENABLE_USER_AUTH=true`;
- file-backed users/sessions;
- PBKDF2 password hash;
- bearer access tokens;
- session TTL через `ACCESS_TOKEN_TTL_MINUTES`;
- logout/revoke текущей сессии;
- cleanup expired sessions;
- `owner_id` и `organization_id` в projects/jobs;
- фильтрация списка проектов по текущему user;
- чужие projects/jobs/files возвращают `404`;
- тесты на изоляцию пользователей.

Ограничения:

- нет password reset;
- нет email verification;
- нет managed auth/OIDC;
- нет refresh tokens;
- нет device/session management UI;
- нет ролей и permissions.

### Audit log

Реализовано:

- file-backed `AuditLogService`;
- запись событий `auth.register`, `auth.login`, `auth.logout`;
- запись событий `project.create`, `project.update`, `project.delete`, `project.duplicate`;
- запись событий `job.start`, `job.cancel`, `job.retry`;
- запись событий `scene.create`, `scene.update`, `scene.delete`, `scene.reorder`;
- `GET /audit/events` с pagination headers;
- фильтрация audit events по `resource_type` и `resource_id`;
- изоляция audit events по текущему bearer user при `ENABLE_USER_AUTH=true`;
- cleanup старых audit event files через maintenance endpoint;
- mobile API type/client function и UI panel для журнала.

Ограничения:

- audit log пока хранится в локальных JSON-файлах;
- нет immutable DB/WORM storage;
- нет admin-wide audit browser;
- нет policy для support/super-admin просмотра чужих событий;
- нет экспорта audit log и retention policies по типам событий.

### Usage, limits and cost tracking

Реализовано:

- file-backed `UsageService`;
- запись usage events для `project.create`, `project.duplicate`, `job.start`;
- `GET /usage/me` с текущими лимитами, счетчиками и estimated cost;
- конфигурируемый лимит проектов через `USAGE_MAX_PROJECTS_PER_USER`;
- конфигурируемый лимит активных job через `USAGE_MAX_ACTIVE_JOBS_PER_USER`;
- простая cost-модель через `USAGE_LLM_JOB_COST_CENTS`, `USAGE_TTS_COST_CENTS_PER_MINUTE`, `USAGE_RENDER_COST_CENTS_PER_MINUTE`;
- `402 project_quota_exceeded` при превышении лимита проектов;
- `402 active_job_quota_exceeded` при превышении лимита активных job;
- cleanup старых usage event files;
- mobile usage panel.

Ограничения:

- это MVP-лимиты, не полноценный Stripe billing;
- нет подписок, invoice, payment methods и webhooks;
- нет тарифных планов и промокодов;
- cost tracking оценочный, не сверяется с реальными provider invoices;
- usage ledger пока хранится в локальных JSON-файлах.

### Генерация видео

Реализовано:

- template script generator;
- optional OpenAI LLM provider для сценария;
- fallback на template при ошибке LLM;
- user source URLs плюс curated/fallback sources;
- SSRF guard для source URLs;
- optional browser screenshots;
- Pillow PNG slides;
- placeholder WAV voice;
- optional OpenAI TTS;
- SRT/VTT captions;
- avatar placeholder step;
- FFmpeg render в MP4;
- render timeout;
- thumbnail, title options, YouTube metadata, quality report;
- export ZIP package с проверкой project directory.

Ограничения:

- нет настоящего search provider;
- нет fact-checking/research context;
- нет Remotion/advanced templates;
- avatar provider не подключен;
- voice clone и consent flow отсутствуют;
- source approval UI отсутствует.

### Job system

Реализовано:

- file-backed job store;
- local `ThreadPoolExecutor`;
- inline mode для тестов/локального режима;
- active job deduplication per project;
- progress events;
- cancel queued/running job;
- retry terminal job;
- cleanup old jobs;
- owner_id у jobs;
- pagination job lists/events.

Ограничения:

- job queue не durable для production;
- нет Redis/Celery/RQ/BullMQ/Temporal;
- нет per-user concurrency limits;
- нет cost accounting;
- нет WebSocket/SSE push;
- нет distributed workers.

### Mobile MVP

Реализовано:

- настройка API base URL и public API key;
- bearer token storage через Expo SecureStore с восстановлением сессии через `/auth/me`;
- register/login/logout/me;
- создание проекта;
- список проектов;
- открытие проекта и manifest;
- запуск job и polling;
- cancel/retry;
- duplicate/delete project;
- scene selection;
- edit scene title/narration/duration;
- add/delete/regenerate scene slide;
- scene reorder через move up/down;
- Idempotency-Key на create/start/duplicate;
- pagination defaults для projects/job events;
- audit log panel;
- usage/limits/cost summary panel.

Ограничения:

- нет refresh token rotation/device session UI;
- UI пока MVP, без полноценной навигации и production UX;
- нет push/SSE, только polling;
- нет upload/asset manager;
- нет Stripe billing/admin screens.

### Infrastructure и CI

Реализовано:

- Dockerfile backend;
- docker-compose backend service;
- non-root Docker user;
- runtime/dev dependency split;
- backend tests;
- mobile TypeScript check;
- pip-audit для backend runtime;
- secret scan script;
- production API key validation;
- `.env.example`/docs для OS SOTA integration.

Ограничения:

- нет deployment manifests для cloud;
- нет managed database;
- нет object storage;
- нет backup/restore;
- нет monitoring stack;
- нет centralized logs/traces.

## 5. Интеграции

Используются или предусмотрены:

- OpenAI LLM: optional script provider, включается `OPENAI_API_KEY`.
- OpenAI TTS: optional voice provider, включается `OPENAI_API_KEY`.
- FFmpeg: обязательный render binary, есть fallback через bundled resolver.
- Playwright/browser screenshots: optional через `ENABLE_BROWSER_SCREENSHOTS`.
- OS SOTA integration files: client/smoke scripts и env example присутствуют в корне.
- Expo/React Native: мобильный MVP.
- Docker/GitHub Actions: сборка и проверки.

Не подключены production-интеграции:

- Stripe/платежи;
- Postgres;
- Redis/queue;
- S3/R2;
- Sentry/OTel/Prometheus;
- SendGrid/Resend/SMS;
- HeyGen/D-ID/Tavus;
- ElevenLabs/Azure voice;
- OAuth/OIDC providers.

## 6. Основные риски

### P0/P1 для production

1. Локальные JSON-файлы вместо DB.
2. Локальная job queue вместо durable queue.
3. Локальное файловое хранилище вместо object storage.
4. Нет RBAC/organizations/roles.
5. Нет Stripe billing/subscriptions; usage limits есть только как MVP foundation.
6. Audit log есть только file-backed MVP, без immutable storage/admin-wide browser.
7. Нет observability и alerting.
8. Нет backup/restore процесса.
9. Нет legal consent для voice/avatar.
10. Нет managed mobile session/device controls поверх SecureStore.

### P2 для beta

1. Нужен нормальный source/research provider.
2. Нужен экран review/approval для сценария, источников и визуалов.
3. Нужен source confidence score.
4. Нужны SSE/WebSocket progress events.
5. Нужны API response models/OpenAPI polish.
6. Нужны e2e smoke tests backend-mobile.
7. Нужно улучшить UX мобильного редактора сцен.
8. Нужны production тарифы и provider-verified cost reconciliation.

### P3 улучшения качества

1. Remotion/шаблоны вместо простых Pillow slides.
2. Presets 16:9 / 9:16 / 1:1.
3. Preview render.
4. Better subtitles styling.
5. Real avatar overlay.
6. Manual asset replacement.
7. Export/publish workflow для YouTube.

## 7. Что понятно по коду

Понятно:

- backend разделен на routes, models, storage, services, utils;
- pipeline читается последовательно и хорошо подходит для MVP;
- job model достаточно прозрачен;
- security checks локализованы в utils;
- auth вынесен в отдельный сервис;
- mobile API client централизован;
- docs уже описывают большую часть поверхности.

Не до конца понятно или требует архитектурного решения:

- какой production auth provider будет выбран;
- какая целевая DB schema и миграционная стратегия;
- будет ли web-приложение отдельно от mobile;
- какой провайдер очередей нужен: Celery/RQ/Temporal/BullMQ;
- нужен ли multi-tenant org model сразу или после beta;
- какая модель тарифов и лимитов;
- какой уровень юридического compliance нужен для voice/avatar;
- как будет устроен publish flow в YouTube.

## 8. План доработок по очереди

### Этап 1 - стабилизация API и UX MVP

Статус: частично выполнено.

- pagination/idempotency/error contract: выполнено;
- закрепить response models для OpenAPI;
- добавить больше API tests на auth + idempotency + pagination;
- добавить mobile secure token persistence;
- добавить UI pagination/load more;
- добавить экран job events/progress details.

### Этап 2 - PostgreSQL

- спроектировать schema: users, sessions, organizations, memberships, projects, scenes, sources, jobs, artifacts;
- добавить Alembic migrations;
- заменить JSON project/job/auth storage на repository layer;
- добавить indexes по owner/status/updated_at;
- сохранить file-backed mode как local fallback только при необходимости.

### Этап 3 - durable queue

- выбрать Celery/RQ/Temporal/BullMQ;
- вынести workers отдельно от API;
- сделать per-user concurrency;
- retry/backoff/dead-letter;
- progress events через DB/Redis;
- SSE/WebSocket endpoint для live progress.

### Этап 4 - object storage

- S3/R2 adapter;
- artifact model;
- signed URLs;
- lifecycle/retention policies;
- migrate `/files` на signed asset URLs;
- audit access to private artifacts.

### Этап 5 - production auth/RBAC

- managed auth/OIDC или hardened internal auth;
- organizations/teams;
- roles: owner/admin/editor/viewer/support;
- policy layer для каждой операции;
- audit log;
- session/device management;
- password reset/email verification если internal auth остается.

### Этап 6 - real research and AI сценарист

- search provider;
- canonical URL/domain validation;
- confidence score;
- source review/approval;
- LLM JSON repair/retry;
- factual context перед генерацией сценария;
- metadata/chapters/CTA через LLM.

### Этап 7 - render/voice/avatar upgrade

- Remotion или другой production render template engine;
- animated transitions/highlights;
- presets 16:9/9:16/1:1;
- OpenAI/ElevenLabs/Azure voice adapters;
- voice profile + consent;
- HeyGen/D-ID/Tavus avatar adapter;
- avatar overlay settings.

### Этап 8 - monetization/admin/observability

- Stripe billing;
- quotas and usage limits;
- cost tracking по LLM/TTS/render;
- admin panel;
- support/moderation workflow;
- metrics/logs/traces/error tracking;
- backup/restore drills;
- incident response docs.

## 9. Итог

Кодовая база стала заметно ближе к серьезному MVP: есть pipeline, mobile flow, auth foundation, ownership, hardening, pagination и idempotency. Самый важный следующий инженерный рубеж - убрать локальную инфраструктуру из критического пути: Postgres, durable queue и object storage. После этого имеет смысл активно расширять роли, биллинг, admin и production render.
