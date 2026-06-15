# Архитектура MVP v0.4

```text
Mobile App / Expo
  ↓ HTTP
Backend API / FastAPI
  ↓
ProjectStore / local JSON files
JobStore / local JSON files
  ↓
JobRunner / ThreadPoolExecutor
  ↓
VideoPipeline
  ├─ ComplianceService
  ├─ ScriptService
  │   ├─ template generator
  │   └─ OpenAILLMProvider optional
  ├─ SourceService
  │   └─ ScreenshotService
  │       ├─ fallback source cards
  │       └─ Playwright optional
  ├─ VoiceService
  │   ├─ placeholder WAV generator
  │   └─ OpenAITTSProvider optional
  ├─ VisualService / Pillow slides
  ├─ AvatarService placeholder
  └─ RenderService / FFmpeg + exports
```

## Security/storage rules

- project/job/scene ids валидируются до использования в файловых путях;
- каждый storage path резолвится и проверяется на принадлежность `DATA_DIR`;
- JSON-файлы пишутся атомарно через temp-file + replace;
- `/files/{path}` работает как контролируемый endpoint, а не raw static mount;
- `API_KEY` опционально защищает непубличные routes через `X-API-Key`;
- source URLs проверяются перед browser screenshots, private/local networks заблокированы по умолчанию.

## Зачем v0.4

В v0.3 был production-подобный provider layer:

```text
LLMProvider
TTSProvider
metadata/export layer
quality report
mobile provider toggles
```

v0.4 добавляет слой, без которого мобильное приложение неудобно использовать для долгих операций:

```text
JobStore
JobRunner
queued generation
progress polling
scene insert/delete/reorder
duplicate project
```

При этом проект всё ещё запускается офлайн без платных ключей.

## Backend modules

```text
app/models.py       — Pydantic-модели проекта, сцен, источников, результатов и jobs
app/storage.py      — локальное JSON-хранилище проектов + scene editor operations
app/pipeline.py     — оркестрация шагов генерации
app/main.py         — FastAPI endpoints
```

Сервисы:

```text
ComplianceService   — блокирует YouTube-кадры и risky prompts
JobStore            — файловое хранилище job_*.json
JobRunner           — локальный ThreadPoolExecutor для job pipeline
ScriptService       — template/OpenAI сценарии
SourceService       — безопасные источники
ScreenshotService   — fallback-карточки / Playwright screenshots
VoiceService        — placeholder/OpenAI TTS + SRT/VTT + manifest
VisualService       — PNG-слайды 1920x1080
AvatarService       — placeholder для будущего avatar provider
RenderService       — FFmpeg render + YouTube export package
```

Provider layer:

```text
services/providers/base.py
services/providers/factory.py
services/providers/openai_provider.py
services/providers/mock.py
```

## Job layer

Job layer нужен, чтобы мобильный клиент мог:

```text
1. создать проект;
2. запустить generate_all как задачу;
3. показывать прогресс;
4. опрашивать GET /jobs/{job_id};
5. получить результат, когда job завершился.
```

Локальный job flow:

```text
POST /projects/{id}/jobs/generate_all
  ↓
JobStore.create(job)
  ↓
Project.status = queued
  ↓
JobRunner.submit(...)
  ↓
generate_script  → progress 15
generate_sources → progress 30
generate_voice   → progress 48
generate_slides  → progress 66
prepare_avatar   → progress 78
render           → progress 95
  ↓
Job.status = completed / failed
```

Настройки:

```text
RUN_JOBS_INLINE=false  — обычный режим API, задача идёт в thread pool;
RUN_JOBS_INLINE=true   — удобный режим для тестов/demo;
JOB_WORKERS=2          — число локальных потоков.
```

Production-замена:

```text
JobStore/JobRunner → Redis + BullMQ / Celery / RQ / Temporal / cloud queue
```

## Provider fallback

LLM/TTS провайдеры подключаются опционально:

```text
script_provider=openai + OPENAI_API_KEY → OpenAI сценарий
script_provider=openai без ключа         → warning + template fallback
voice_provider=openai + OPENAI_API_KEY   → OpenAI TTS
voice_provider=openai без ключа          → warning + placeholder fallback
```

Это сделано, чтобы приложение не ломалось при отсутствии ключей, лимитов или временной недоступности провайдера.

## Безопасные визуальные источники

MVP поддерживает два режима:

```text
ai_slides_only
```

Использует только оригинальные слайды, созданные приложением.

```text
official_sites_plus_ai
```

Использует:

- URL, которые явно указал пользователь;
- curated official websites по теме;
- fallback-карточки источников;
- опциональные браузерные скриншоты через Playwright.

Модуль не скачивает и не маскирует кадры из чужих YouTube-видео.

## Scene editor

v0.4 добавляет операции:

```text
PATCH scene
POST scene
DELETE scene
POST reorder scenes
POST regenerate one slide
```

После изменения длительности backend пересчитывает `start_sec`. После изменения визуальной части очищается `visual_path`. После изменения narration/duration очищаются `audio_path` и subtitle paths, чтобы клиент понимал: нужно заново генерировать голос/субтитры.

## Browser screenshots

По умолчанию:

```text
ENABLE_BROWSER_SCREENSHOTS=false
```

Это сделано специально: архив должен запускаться без браузеров, внешнего интернета и API-ключей. Если флаг включён, `ScreenshotService` пытается открыть URL через Playwright. При ошибке он не ломает pipeline, а возвращается к fallback-card.

## ProjectStore и JobStore

Проекты:

```text
backend/data/projects/<project_id>/project.json
```

Jobs:

```text
backend/data/projects/_jobs/job_*.json
```

Файлы результата:

```text
assets/sources/*.png
slides/*.png
audio/*.wav
video/final.mp4
exports/*.json
exports/*.txt
exports/*.srt
exports/*.vtt
exports/*.png
exports/result_package.zip
```

## Production-версия

```text
React Native / Expo
API Gateway: NestJS или FastAPI
PostgreSQL
Redis Queue / BullMQ / Celery / Temporal
Research Worker
Playwright Screenshot Worker
LLM Worker
TTS Worker
Avatar Worker
Render Worker / Remotion + FFmpeg
S3 / Cloudflare R2
Admin Panel
Billing + limits
```

## Дальнейшее разделение сервисов

```text
ScriptService      → LLMProvider + JSON repair + fact-check layer
SourceService      → SearchProvider + WebsiteResolver + license checker
ScreenshotService  → Playwright cluster / browserless worker
VisualService      → Remotion templates + image generation
VoiceService       → TTSProvider + VoiceProfile + consent flow
AvatarService      → HeyGen/D-ID/Tavus adapter
RenderService      → Remotion/FFmpeg queue worker
Storage            → S3/R2 + signed URLs
ProjectStore       → PostgreSQL models
JobStore           → Redis/PostgreSQL/Temporal workflow history
```
