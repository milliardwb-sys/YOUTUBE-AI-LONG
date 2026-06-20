# API v0.4

Base URL for local development:

```text
http://localhost:8000
```

## Auth

Если задан `API_KEY`, все endpoints кроме `/health`, `/ready`, `/providers`, `/docs`, `/redoc` и `/openapi.json` требуют `X-API-Key: <API_KEY>`. Без ключа сервер отвечает `401`.

Если `APP_ENV` не `local`, `test`, `dev` или `development`, backend требует настроенный `API_KEY` для приватных endpoints. Без ключа приватные routes возвращают `403`, чтобы production-сервер нельзя было случайно запустить открытым.

Если `API_KEY` задан в non-local окружении, backend отклоняет известные placeholder-значения и секреты короче 32 символов.

Optional user auth включается через:

```text
ENABLE_USER_AUTH=true
ACCESS_TOKEN_TTL_MINUTES=1440
```

Когда `ENABLE_USER_AUTH=true`, project, job и project file endpoints требуют:

```text
Authorization: Bearer <access_token>
```

Доступные auth endpoints:

```text
POST /auth/register
POST /auth/login
GET /auth/me
POST /auth/logout
```

Новые проекты получают `owner_id`; список проектов фильтруется по текущему пользователю; чужие projects/jobs/files возвращают `404`. Это MVP file-backed auth foundation. Для production всё ещё нужны managed auth/OIDC, organizations, roles, audit logs и database-backed sessions.

`POST /auth/logout` revokes the current bearer session. `POST /maintenance/cleanup` also removes expired auth session files and returns `removed_sessions` / `skipped_sessions`.

## Audit log

Backend writes local audit events for core user/project/job/scene actions:

```text
auth.register
auth.login
auth.logout
project.create
project.update
project.delete
project.duplicate
job.start
job.cancel
job.retry
scene.create
scene.update
scene.delete
scene.reorder
```

Events are available through:

```text
GET /audit/events?limit=100&offset=0
GET /audit/events?resource_type=project&resource_id=project_...
```

When `ENABLE_USER_AUTH=true`, this endpoint returns only events created by the current bearer user. When user auth is disabled, it returns local MVP-wide events and is protected by the same API key middleware as other private endpoints. `POST /maintenance/cleanup` removes old audit event files and returns `removed_audit_events` / `skipped_audit_events`.

## Usage, limits and cost tracking

Backend keeps a local file-backed usage ledger for MVP billing/limits foundations. Current usage is available through:

```text
GET /usage/me
```

The response includes current project count, active job count, usage event totals and estimated cost in cents:

```json
{
  "actor_id": "user_...",
  "limits": {
    "max_projects": 25,
    "max_active_jobs": 2,
    "current_projects": 1,
    "current_active_jobs": 0
  },
  "usage": {
    "event_count": 2,
    "total_units": 2,
    "estimated_cost_cents": 3,
    "events_by_action": {
      "project.create": 1,
      "job.start": 1
    }
  }
}
```

Config:

```text
USAGE_MAX_PROJECTS_PER_USER=25
USAGE_MAX_ACTIVE_JOBS_PER_USER=2
USAGE_LLM_JOB_COST_CENTS=1
USAGE_TTS_COST_CENTS_PER_MINUTE=1
USAGE_RENDER_COST_CENTS_PER_MINUTE=2
```

`0` disables a limit. Project creation and project duplication return `402` with `project_quota_exceeded` when the project quota is exhausted. Starting a new job returns `402` with `active_job_quota_exceeded` when the active job quota is exhausted. Existing active jobs for the same project are reused instead of counted as new jobs.

## Backups and restore preview

Local file-backed deployments can create data snapshots through maintenance endpoints:

```text
POST /maintenance/backups
GET /maintenance/backups
GET /maintenance/backups/{backup_id}
POST /maintenance/backups/{backup_id}/restore-preview
```

`POST /maintenance/backups` creates a ZIP snapshot of `DATA_DIR`, excluding internal `_backups` and `_restores` folders. `GET /maintenance/backups/{backup_id}` downloads the ZIP.

Restore is intentionally a preview operation in the MVP: `restore-preview` extracts the backup into `DATA_DIR/_restores/<restore_id>` and does not overwrite live project/job/auth data. This gives a safe restore drill before a future production restore flow with explicit operator approval.

## Observability metrics

Backend exposes lightweight in-memory request metrics:

```text
GET /observability/metrics
```

The response includes uptime, total requests, average/max latency, requests by status code, and top request paths. This is an MVP observability layer; production should still add centralized logs, traces, metrics storage, dashboards and alerts.

## Rate limiting

Встроенный in-memory limiter включается через:

```text
RATE_LIMIT_REQUESTS_PER_MINUTE=120
```

`0` отключает limiter. Лимит считается на минутное окно по `X-API-Key`, если он передан, иначе по IP клиента. При превышении backend возвращает `429` и headers:

```text
X-RateLimit-Limit
X-RateLimit-Remaining
X-RateLimit-Reset
Retry-After
```

Для полноценного production лучше дополнительно использовать внешний API Gateway / reverse proxy limiter.

## Request size limit

`MAX_REQUEST_BODY_BYTES` limits incoming request body size by `Content-Length`. Requests over the limit return `413`.

```text
MAX_REQUEST_BODY_BYTES=2000000
```

## Pagination

List endpoints keep the old response shape as a JSON array, but now support bounded pagination:

```text
GET /projects?limit=50&offset=0
GET /projects/{id}/jobs?limit=50&offset=0
GET /jobs/{job_id}/events?limit=100&offset=0
GET /audit/events?limit=100&offset=0
```

Responses include:

```text
X-Total-Count
X-Limit
X-Offset
```

`limit` is capped by the backend: projects/jobs up to `200`, job events up to `500`.

## Idempotency

Retry-sensitive POST endpoints accept:

```text
Idempotency-Key: <stable-client-generated-key>
```

Currently supported:

```text
POST /projects
POST /projects/{id}/duplicate
POST /projects/{id}/jobs/{job_type}
POST /projects/{id}/generate-all-queued
```

The same key with the same request returns the original project/job and adds:

```text
X-Idempotent-Replay: true
```

The same key reused for a different request returns `409`. Keys must be 8-128 characters and may contain letters, digits, `.`, `_`, `:` and `-`.

## Error contract

All HTTP errors keep the legacy `detail` field and also include a structured `error` object:

```json
{
  "detail": "Project not found",
  "error": {
    "status_code": 404,
    "message": "Project not found",
    "request_id": "req_..."
  }
}
```

Синхронные pipeline endpoints возвращают HTTP-ошибку, если шаг не выполнен: `400` для compliance, `404` для not found, `409` для precondition failure и `500` для runtime/render/provider failure. Job endpoints отдают ошибки через `GET /jobs/{job_id}`.

`RENDER_TIMEOUT_SECONDS` ограничивает длительность FFmpeg-render. При timeout проект/job завершается ошибкой вместо бесконечного удержания worker.

## GET /health

Проверяет, что backend работает.

```json
{
  "status": "ok",
  "version": "0.4.0",
  "env": "local",
  "browser_screenshots": false,
  "openai_configured": false,
  "model_images_enabled": false,
  "heygen_configured": false,
  "run_jobs_inline": false,
  "job_workers": 2,
  "render_timeout_seconds": 1800,
  "user_auth_enabled": false,
  "max_request_body_bytes": 2000000
}
```

## GET /projects/{id}/manifest

Returns a project readiness manifest for audit, UI checks, and publish preflight.

The manifest includes project status, scene/source counts, avatar video counts, scenes with visuals and audio, expected/ready/missing artifacts, per-artifact file existence and size, and readiness flags for script, sources, visuals, voice, avatars, render, export package, and final publish readiness.

```json
{
  "project_id": "project_...",
  "status": "completed",
  "current_step": "completed",
  "counts": {
    "scenes": 8,
    "sources": 4,
    "scenes_with_visuals": 8,
    "scenes_with_audio": 8,
    "avatar_scenes": 4,
    "avatar_videos_submitted": 4,
    "avatar_videos_ready_remote": 4,
    "avatar_videos_downloaded": 4,
    "avatar_videos_failed": 0,
    "expected_artifacts": 14,
    "ready_artifacts": 14,
    "missing_artifacts": 0
  },
  "readiness": {
    "script": true,
    "sources": true,
    "visuals": true,
    "voice": true,
    "avatars": true,
    "render": true,
    "export_package": true,
    "publish_ready": true
  },
  "missing_artifacts": []
}
```

## GET /providers

Показывает доступные provider-настройки и job-настройки.

```json
{
  "script": {
    "available": ["template", "openai"],
    "default": "template",
    "openai_configured": false,
    "openai_model": "gpt-4.1-mini"
  },
  "voice": {
    "available": ["placeholder", "openai"],
    "default": "placeholder",
    "openai_configured": false,
    "openai_tts_model": "gpt-4o-mini-tts",
    "openai_tts_voice": "alloy"
  },
  "screenshots": {
    "browser_enabled": false,
    "timeout_ms": 12000
  },
  "visuals": {
    "model_images_enabled": false,
    "openai_image_model": "gpt-image-1",
    "openai_image_size": "1536x1024"
  },
  "avatar": {
    "provider": "heygen",
    "configured": false,
    "resolution": "1080p",
    "output_format": "mp4",
    "remove_background": true,
    "motion_prompt_enabled": false,
    "auto_sync_enabled": false,
    "auto_sync_interval_seconds": 60,
    "auto_render_after_sync": true
  },
  "jobs": {
    "available": [
      "generate_script",
      "collect_sources",
      "generate_slides",
      "generate_voice",
      "prepare_avatar",
      "sync_avatar",
      "render",
      "generate_all"
    ],
    "run_inline": false,
    "workers": 2
  }
}
```

## GET /stats

Возвращает компактную статистику MVP-хранилища и job queue.

```json
{
  "status": "ok",
  "version": "0.4.0",
  "env": "local",
  "storage": {
    "project_count": 3,
    "projects_by_status": {
      "completed": 1,
      "draft": 2
    },
    "storage_files": 42,
    "storage_bytes": 10485760
  },
  "jobs": {
    "job_count": 4,
    "active_jobs": 1,
    "terminal_jobs": 3,
    "jobs_by_status": {
      "running": 1,
      "completed": 2,
      "cancelled": 1
    },
    "jobs_by_type": {
      "generate_all": 4
    }
  }
}
```

## POST /projects

Создаёт проект.

```json
{
  "topic": "AI-аватар показывает 5 сервисов для создания YouTube-видео в 2026 году",
  "duration_minutes": 3,
  "style": "ai_news_avatar",
  "language": "ru",
  "audience": "создатели YouTube-каналов",
  "visual_mode": "official_sites_plus_ai",
  "source_urls": ["https://www.heygen.com/", "https://runwayml.com/", "https://www.synthesia.io/"],
  "avatar_enabled": true,
  "avatar_position": "bottom_left",
  "script_provider": "template",
  "voice_provider": "placeholder",
  "voice_id": "alloy",
  "brand_theme": "neon",
  "burn_subtitles": true
}
```

### Основные enum-поля

`style`:

```text
expert_review   — экспертный обзор;
tutorial        — обучающий ролик;
top_list        — топ-подборка;
trend_analysis  — анализ тренда;
sales_video     — продающее видео;
ai_news_avatar  — AI-ведущий: fullscreen avatar, PIP, screen demo, AI b-roll, CTA.
```

`visual_mode`:

```text
ai_slides_only          — только оригинальные AI-слайды;
official_sites_plus_ai  — официальные сайты / user URLs + AI-слайды.
```

`script_provider`:

```text
template — офлайн-шаблон;
openai   — optional LLM-provider, нужен OPENAI_API_KEY.
```

`voice_provider`:

```text
placeholder — локальная WAV-заглушка;
openai      — optional TTS-provider, нужен OPENAI_API_KEY.
```

`brand_theme`:

```text
dark
light
neon
```

## GET /projects

Список проектов, новые сверху.

```text
GET /projects?limit=50&offset=0
```

Ответ остаётся массивом проектов. Общее количество доступно в `X-Total-Count`.

## GET /projects/{id}

Полная карточка проекта: настройки, сцены, источники, warnings и ссылки на файлы.

## PATCH /projects/{id}

Обновляет настройки проекта.

```json
{
  "topic": "Новая тема",
  "duration_minutes": 5,
  "visual_mode": "official_sites_plus_ai",
  "script_provider": "openai",
  "voice_provider": "openai",
  "brand_theme": "light"
}
```

## DELETE /projects/{id}

Удаляет проект и его локальные файлы.

## POST /projects/{id}/duplicate

Создаёт копию проекта. По умолчанию копия очищается от сцен, источников и файлов результата, чтобы её можно было сгенерировать заново.

## Job endpoints

### POST /projects/{id}/jobs/{job_type}

Запускает задачу генерации. Поддерживаемые `job_type`:

```text
generate_script
collect_sources
generate_slides
generate_voice
prepare_avatar
sync_avatar
render
generate_all
```

Пример:

```bash
curl -X POST http://localhost:8000/projects/<project_id>/jobs/generate_all
```

Для фонового обновления HeyGen-статусов и скачивания готовых avatar MP4:

```bash
curl -X POST http://localhost:8000/projects/<project_id>/jobs/sync_avatar
```

Ответ:

```json
{
  "id": "job_...",
  "project_id": "project_...",
  "type": "generate_all",
  "status": "queued",
  "progress": 0,
  "current_step": "queued",
  "error": null
}
```

### POST /projects/{id}/generate-all-queued

Alias для:

```text
POST /projects/{id}/jobs/generate_all
```

Если у проекта уже есть `queued` или `running` job, backend вернёт существующую активную job вместо запуска второй параллельной генерации.

Для защиты от повторного запуска при сетевом retry можно передать `Idempotency-Key`.

### GET /jobs/{job_id}

Возвращает статус job.

```json
{
  "id": "job_...",
  "project_id": "project_...",
  "type": "generate_all",
  "status": "running",
  "progress": 66,
  "current_step": "finished_generate_slides",
  "error": null,
  "events": [
    {
      "event": "queued",
      "message": "queued_generate_all",
      "progress": 0,
      "created_at": "2026-06-16T10:00:00+00:00"
    }
  ],
  "result_project_status": null
}
```

### POST /jobs/{job_id}/cancel

Отменяет `queued` или `running` job.

В текущем MVP отмена кооперативная: backend помечает job как `cancelled`, а локальный runner останавливается перед следующим шагом pipeline. Уже начатый тяжёлый шаг не прерывается силой, потому что текущая очередь работает через локальный `ThreadPoolExecutor`, а не через отдельный production worker.

Ответ:

```json
{
  "id": "job_...",
  "project_id": "project_...",
  "type": "generate_all",
  "status": "cancelled",
  "progress": 30,
  "current_step": "cancelled",
  "error": "Job cancelled by user"
}
```

Если job уже `completed`, `failed` или `cancelled`, endpoint вернёт `409`.

### POST /jobs/{job_id}/retry

Создаёт новую job того же типа для того же проекта на основе завершённой, failed или cancelled job.

Активные `queued` и `running` jobs нельзя retry-ить; для них endpoint вернёт `409`.

### GET /projects/{id}/jobs

Возвращает список задач проекта, новые сверху.

```text
GET /projects/{id}/jobs?limit=50&offset=0
```

### GET /jobs/{job_id}/events

Возвращает историю событий job: постановка в очередь, запуск, progress steps, отмена, retry, failed/completed.

```text
GET /jobs/{job_id}/events?limit=100&offset=0
```

```json
[
  {
    "event": "progress",
    "message": "finished_generate_slides",
    "progress": 66,
    "created_at": "2026-06-16T10:01:30+00:00"
  }
]
```

## Синхронные pipeline endpoints

Эти endpoints выполняют работу в рамках HTTP-запроса. Они удобны для demo и тестов.

### POST /projects/{id}/generate-script

Генерирует сцены и текст диктора.

Логика:

```text
script_provider=template → локальный шаблон;
script_provider=openai   → OpenAI LLM; если ошибка, fallback на template + warning.
```

### POST /projects/{id}/collect-sources

Создаёт список безопасных источников:

- user-provided URLs;
- curated official websites по теме;
- fallback-карточки источников;
- опциональные браузерные скриншоты при `ENABLE_BROWSER_SCREENSHOTS=true`.

### POST /projects/{id}/generate-voice

Создаёт аудио по сценам, `subtitles.srt`, `captions.vtt` и `voice_manifest.json`.

Логика:

```text
voice_provider=placeholder → локальная WAV-заглушка;
voice_provider=openai      → OpenAI TTS; если ошибка, fallback на placeholder + warning.
```

### POST /projects/{id}/generate-slides

Создаёт PNG-визуалы 16:9 и `visual_assets_manifest.json`.

Типы слайдов:

```text
ai_slide
screenshot
table
diagram
avatar_fullscreen
avatar_pip
screen_demo
ai_broll
big_caption
cta
```

Для `screen_demo` backend использует user URLs, search/curated official websites и fallback-карточки источников. Для `ai_broll` можно включить `ENABLE_MODEL_IMAGES=true`, тогда backend попробует создать оригинальную картинку через `OPENAI_IMAGE_MODEL`; при ошибке остаётся offline-template.

### POST /projects/{id}/prepare-avatar

Готовит avatar-сцены через HeyGen или fallback-манифест.

Логика:

```text
HEYGEN_API_KEY + HEYGEN_AVATAR_ID заданы → POST /v3/videos для avatar-сцен;
ключи не заданы → avatar_manifest.json со статусом placeholder/provider_not_configured.
```

Для сцен `avatar_fullscreen`, `avatar_pip`, `screen_demo` и `cta` backend сохраняет `avatar_video_id`, `avatar_video_status`, `avatar_video_url` и, если доступен готовый файл, `avatar_video_path`. Если у сцены есть локальный `avatar_video_path`, `render` использует avatar-video compositor: fullscreen-сцены берут видео аватара как основной кадр, PIP/screen/CTA-сцены накладывают видео поверх PNG-визуала.
`HEYGEN_ENABLE_MOTION_PROMPT=false` по умолчанию: motion prompt включается вручную, потому что HeyGen поддерживает его не для всех avatar engine/avatar types.

### POST /projects/{id}/sync-avatar

Проверяет статусы уже созданных HeyGen-задач, обновляет `avatar_video_status/avatar_video_url` и скачивает готовые MP4 в `assets/avatar`.

Важно: endpoint не создаёт новые HeyGen-задачи для сцен без `avatar_video_id`. Для первичной отправки используйте `prepare-avatar`, для повторной генерации одной сцены — `retry-avatar`.

### POST /projects/{id}/scenes/{scene_id}/retry-avatar

Сбрасывает у выбранной avatar-сцены старые `avatar_video_id`, `avatar_video_status`, `avatar_video_url`, `avatar_video_path` и отправляет в HeyGen только эту сцену.

Если сцена не относится к `avatar_fullscreen`, `avatar_pip`, `screen_demo` или `cta`, API вернёт `409`.

### POST /projects/{id}/render

Собирает `final.mp4` через FFmpeg и создаёт export package. Если локальные avatar MP4 отсутствуют, используется обычный slideshow render. Если есть `avatar_video_path`, backend рендерит per-scene segments и собирает avatar composite video.

Если `FFMPEG_BIN` отсутствует в PATH, backend пробует bundled fallback из `imageio-ffmpeg`. Если ни один FFmpeg binary не найден, проект получает `failed`, но backend всё равно создаёт manifest/export package с доступными артефактами. В синхронном HTTP endpoint это будет `500`; в job mode ошибка попадёт в `job.error`.

Результаты:

```text
final.mp4
subtitles.srt
captions.vtt
description.txt
sources.json
storyboard.json
thumbnail_prompt.txt
thumbnail.png
title_options.txt
youtube_metadata.json
quality_report.json
voice_manifest.json
avatar_manifest.json
visual_assets_manifest.json
render_manifest.json
result_package.zip
```

## POST /maintenance/cleanup

Удаляет completed/failed проекты и job-файлы старше `CLEANUP_RETENTION_DAYS`. Running/queued jobs не удаляются.

### POST /projects/{id}/generate-all

Синхронно выполняет полный pipeline:

```text
generate-script
collect-sources
generate-voice
generate-slides
prepare-avatar
render
```

## Scene editor endpoints

Поддерживаемые `visual_type`: `ai_slide`, `screenshot`, `table`, `diagram`, `avatar_fullscreen`, `avatar_pip`, `screen_demo`, `ai_broll`, `big_caption`, `cta`.

### PATCH /projects/{id}/scenes/{scene_id}

Редактирует сцену.

```json
{
  "title": "Новый хук",
  "goal": "зацепить зрителя",
  "narration": "Обновлённый текст диктора...",
  "on_screen_text": "AI-видео: что выбрать",
  "visual_type": "screen_demo",
  "duration_sec": 20,
  "avatar_visible": true,
  "visual_prompt": "neon SaaS explainer slide with huge readable title"
}
```

После смены длительности backend пересчитывает `start_sec` для следующих сцен. Если меняется визуальная часть, `visual_path` очищается. Если меняется narration/duration, `audio_path` и subtitle paths очищаются.

### POST /projects/{id}/scenes

Вставляет новую сцену.

```json
{
  "title": "Ручная вставка",
  "goal": "добавить пояснение",
  "narration": "Текст озвучки для новой сцены.",
  "duration_sec": 12,
  "visual_type": "diagram",
  "order": 2
}
```

Можно использовать `after_scene_id` вместо `order`.

### DELETE /projects/{id}/scenes/{scene_id}

Удаляет сцену и пересчитывает порядок/таймкоды.

### POST /projects/{id}/scenes/reorder

Переставляет сцены. Нужно передать все scene ids в новом порядке.

```json
{
  "scene_ids": ["scene_a", "scene_b", "scene_c"]
}
```

### POST /projects/{id}/scenes/{scene_id}/regenerate-slide

Перегенерирует только один PNG-слайд после правки сцены.

## GET /projects/{id}/status

Возвращает текущий статус и последний job.

```json
{
  "id": "project_...",
  "status": "rendering",
  "current_step": "rendering",
  "error": null,
  "warnings": [],
  "scene_count": 8,
  "source_count": 6,
  "latest_job": {
    "id": "job_...",
    "status": "running",
    "progress": 95
  }
}
```

## GET /projects/{id}/result

Возвращает ссылки на результат.

```json
{
  "final_video_url": "http://localhost:8000/files/.../final.mp4",
  "subtitles_url": "http://localhost:8000/files/.../subtitles.srt",
  "captions_vtt_url": "http://localhost:8000/files/.../captions.vtt",
  "description_url": "http://localhost:8000/files/.../description.txt",
  "sources_url": "http://localhost:8000/files/.../sources.json",
  "storyboard_url": "http://localhost:8000/files/.../storyboard.json",
  "thumbnail_prompt_url": "http://localhost:8000/files/.../thumbnail_prompt.txt",
  "thumbnail_url": "http://localhost:8000/files/.../thumbnail.png",
  "title_options_url": "http://localhost:8000/files/.../title_options.txt",
  "youtube_metadata_url": "http://localhost:8000/files/.../youtube_metadata.json",
  "quality_report_url": "http://localhost:8000/files/.../quality_report.json",
  "voice_manifest_url": "http://localhost:8000/files/.../voice_manifest.json",
  "avatar_manifest_url": "http://localhost:8000/files/.../avatar_manifest.json",
  "visual_assets_manifest_url": "http://localhost:8000/files/.../visual_assets_manifest.json",
  "render_manifest_url": "http://localhost:8000/files/.../render_manifest.json",
  "export_package_url": "http://localhost:8000/files/.../result_package.zip"
}
```
