# API v0.4

Base URL for local development:

```text
http://localhost:8000
```

## Auth

Если задан `API_KEY`, все endpoints кроме `/health`, `/ready`, `/providers`, `/docs`, `/redoc` и `/openapi.json` требуют `X-API-Key: <API_KEY>`. Без ключа сервер отвечает `401`.

Если `APP_ENV` не `local`, `test`, `dev` или `development`, backend требует настроенный `API_KEY` для приватных endpoints. Без ключа приватные routes возвращают `403`, чтобы production-сервер нельзя было случайно запустить открытым.

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

## Error contract

Синхронные pipeline endpoints возвращают HTTP-ошибку, если шаг не выполнен: `400` для compliance, `404` для not found, `409` для precondition failure и `500` для runtime/render/provider failure. Job endpoints отдают ошибки через `GET /jobs/{job_id}`.

## GET /health

Проверяет, что backend работает.

```json
{
  "status": "ok",
  "version": "0.4.0",
  "env": "local",
  "browser_screenshots": false,
  "openai_configured": false,
  "run_jobs_inline": false,
  "job_workers": 2
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
  "jobs": {
    "available": [
      "generate_script",
      "collect_sources",
      "generate_slides",
      "generate_voice",
      "prepare_avatar",
      "render",
      "generate_all"
    ],
    "run_inline": false,
    "workers": 2
  }
}
```

## POST /projects

Создаёт проект.

```json
{
  "topic": "5 AI-сервисов для создания видео в 2026 году",
  "duration_minutes": 3,
  "style": "expert_review",
  "language": "ru",
  "audience": "создатели YouTube-каналов",
  "visual_mode": "official_sites_plus_ai",
  "source_urls": ["https://www.heygen.com/", "https://runwayml.com/"],
  "avatar_enabled": false,
  "avatar_position": "bottom_right",
  "script_provider": "template",
  "voice_provider": "placeholder",
  "voice_id": "alloy",
  "brand_theme": "neon",
  "burn_subtitles": false
}
```

### Основные enum-поля

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

Список проектов.

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
render
generate_all
```

Пример:

```bash
curl -X POST http://localhost:8000/projects/<project_id>/jobs/generate_all
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

### GET /jobs/{job_id}/events

Возвращает историю событий job: постановка в очередь, запуск, progress steps, отмена, retry, failed/completed.

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

Создаёт PNG-слайды 16:9.

Типы слайдов:

```text
ai_slide
screenshot
table
diagram
```

### POST /projects/{id}/prepare-avatar

В v0.4 это placeholder-шаг. Он добавляет warning, если `avatar_enabled=true`, но внешний avatar-provider ещё не подключён.

### POST /projects/{id}/render

Собирает `final.mp4` через FFmpeg и создаёт export package.

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

### PATCH /projects/{id}/scenes/{scene_id}

Редактирует сцену.

```json
{
  "title": "Новый хук",
  "goal": "зацепить зрителя",
  "narration": "Обновлённый текст диктора...",
  "on_screen_text": "AI-видео: что выбрать",
  "visual_type": "ai_slide",
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
  "render_manifest_url": "http://localhost:8000/files/.../render_manifest.json",
  "export_package_url": "http://localhost:8000/files/.../result_package.zip"
}
```
