# AI Video Studio MVP v0.4

Рабочий каркас приложения для генерации YouTube-роликов по теме.

Цель MVP:

```text
тема → job queue → сценарий LLM/шаблон → безопасные источники → слайды → TTS/заглушка → MP4 → YouTube-пакет
```

В архиве есть:

- backend API на FastAPI;
- файловое хранилище проектов;
- локальная job-система для долгих генераций;
- генерация проекта через синхронный endpoint или через job queue;
- генератор сценария без внешнего AI API;
- опциональный LLM-провайдер OpenAI для сценариев;
- опциональная генерация AI b-roll картинок через OpenAI Images;
- безопасный fallback на шаблонный сценарий, если API-ключа нет или провайдер упал;
- безопасный `SourceService`: user URLs + curated official websites;
- `ScreenshotService` с офлайн fallback-карточками источников;
- опциональный браузерный screenshot-capture через Playwright;
- генератор 16:9 PNG-слайдов через Pillow;
- режимы визуалов: `ai_slide`, `screenshot`, `table`, `diagram`, `avatar_fullscreen`, `avatar_pip`, `screen_demo`, `ai_broll`, `big_caption`, `cta`;
- генератор WAV-аудио-заглушек;
- опциональный OpenAI TTS-провайдер для озвучки;
- `voice_manifest.json` с информацией по аудио каждой сцены;
- `avatar_manifest.json` для HeyGen-задач и fallback-аватаров;
- `visual_assets_manifest.json` для скриншотов платформ, model images и offline-шаблонов;
- экспорт SRT и VTT;
- рендер MP4 через FFmpeg;
- thumbnail PNG + prompt для обложки;
- `youtube_metadata.json` с title options, tags, chapters и description;
- `quality_report.json` для ручной проверки перед публикацией;
- export package `result_package.zip`;
- compliance-проверка, которая не даёт использовать чужие YouTube-кадры;
- endpoints для вставки, удаления, перестановки, редактирования сцен;
- endpoint для дублирования проекта;
- endpoint для перегенерации одного слайда;
- обновлённая заготовка Expo-приложения с polling job progress;
- документация по API, архитектуре и следующим шагам.

Подробное описание продукта, схемы работы и интеграций: [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md).

## Что важно

Это **не финальный production-продукт**, а кодовый каркас. Он специально сделан так, чтобы запускаться без платных AI-провайдеров, без внешнего интернета и без браузера.

По умолчанию:

```text
script_provider = template
voice_provider  = placeholder
ENABLE_BROWSER_SCREENSHOTS = false
RUN_JOBS_INLINE = false
API_KEY =
ENABLE_USER_AUTH = false
```

То есть архив можно запустить локально, получить слайды, аудио-заглушку и MP4. Если добавить `OPENAI_API_KEY`, можно включить `script_provider=openai`, `voice_provider=openai` и `ENABLE_MODEL_IMAGES=true`. Если добавить `HEYGEN_API_KEY` и `HEYGEN_AVATAR_ID`, шаг `prepare-avatar` начнёт отправлять avatar-сцены в HeyGen.

Если задать `API_KEY`, все endpoints кроме `/health`, `/ready`, `/providers` и документации требуют заголовок `X-API-Key`. CORS настраивается через `CORS_ORIGINS`.

Если задать `ENABLE_USER_AUTH=true`, backend включает file-backed регистрацию/логин, bearer tokens, `owner_id` у проектов/jobs и изоляцию доступа к project files. Это MVP foundation для multi-user режима; для production всё ещё нужны OIDC/managed auth, роли, организации и audit logs.

Важно для деплоя: если `APP_ENV` не `local`, `test`, `dev` или `development`, backend не будет обслуживать приватные endpoints без `API_KEY` и вернёт `403`. Это защита от случайного публичного запуска открытого API.

Для базовой защиты от спама можно задать `RATE_LIMIT_REQUESTS_PER_MINUTE`. Значение `0` отключает встроенный limiter; в production-шаблоне задано `120`.

Модуль источников не скачивает, не скриншотит и не маскирует чужие YouTube-ролики. Для визуалов используются оригинальные AI-слайды, пользовательские URL, официальные публичные страницы и fallback-карточки источников.

## Быстрый запуск backend

Требования:

- Python 3.11+
- FFmpeg в PATH опционально: если `FFMPEG_BIN` не найден, backend использует bundled fallback из `imageio-ffmpeg`

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

For backend tests and dependency audit install dev dependencies:

```bash
pip install -r requirements-dev.txt
```

Проверка:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/providers
python -c "import app.main"
```

## Docker запуск backend

Для production-like запуска используйте Docker Compose:

```bash
cp backend/.env.production.example backend/.env.production
# обязательно замените API_KEY на длинный секрет
# PowerShell secret helper: -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 48 | ForEach-Object {[char]$_})
docker compose up --build
```

Docker Compose now starts PostgreSQL for project metadata and durable job state when `PROJECT_STORAGE_BACKEND=postgres` and `JOB_STORAGE_BACKEND=postgres` are set in `backend/.env.production`.
Generated files still use the `backend-projects` volume through `DATA_DIR`.
Set `ARTIFACT_STORAGE_BACKEND=s3` plus `S3_*` settings to publish result artifacts through S3/R2-compatible object storage.
Set `STRIPE_API_KEY`, `STRIPE_PRO_PRICE_ID`, and `STRIPE_WEBHOOK_SECRET` to enable subscription checkout, customer portal, and billing-based quotas.
Set `ENABLE_USER_AUTH=true` and `OIDC_ENABLED=true` with `OIDC_*` settings to accept managed-auth JWTs from an external OIDC provider.
Replace the example database password before any public deployment.

После старта:

```bash
curl http://127.0.0.1:8000/ready
curl -H "X-API-Key: <API_KEY>" http://127.0.0.1:8000/projects
```

`APP_ENV=production` без `API_KEY` заблокирует приватные endpoints. Если `API_KEY` задан, backend отклонит известные placeholder-значения и секреты короче 32 символов. `RENDER_TIMEOUT_SECONDS` ограничивает длительность FFmpeg-render, чтобы зависший render не занимал worker бесконечно. Данные проектов сохраняются в Docker volume `backend-projects`.

`MAX_REQUEST_BODY_BYTES` ограничивает размер входящего HTTP body по `Content-Length`. Превышение лимита возвращает `413`.

`ENABLE_USER_AUTH=true` можно включить в `backend/.env.production`, если нужен bearer-token login flow:

```bash
curl -X POST http://127.0.0.1:8000/auth/register \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <API_KEY>" \
  -d '{"email":"owner@example.com","password":"strong-password"}'
```

## Demo без HTTP

Синхронный pipeline:

```bash
cd backend
python run_demo.py
```

Job pipeline:

```bash
cd backend
RUN_JOBS_INLINE=true python run_job_demo.py
```

После выполнения появится папка вида:

```text
backend/data/projects/<project_id>/
```

Внутри будут:

```text
project.json
assets/sources/*.png
assets/avatar/avatar_manifest.json
assets/generated_images/*.png
assets/visual_assets_manifest.json
slides/*.png
audio/*.wav
video/final.mp4
exports/description.txt
exports/sources.json
exports/storyboard.json
exports/thumbnail_prompt.txt
exports/thumbnail.png
exports/title_options.txt
exports/youtube_metadata.json
exports/quality_report.json
exports/voice_manifest.json
exports/render_manifest.json
exports/subtitles.srt
exports/captions.vtt
exports/result_package.zip
```

Job-файлы лежат в:

```text
backend/data/projects/_jobs/job_*.json
```

## API flow через job queue

### 1. Создать проект

```bash
curl -X POST http://localhost:8000/projects \
  -H 'Content-Type: application/json' \
  -d '{
    "topic": "AI-аватар показывает 5 сервисов для создания YouTube-видео в 2026 году",
    "duration_minutes": 3,
    "style": "ai_news_avatar",
    "language": "ru",
    "audience": "создатели YouTube-каналов",
    "visual_mode": "official_sites_plus_ai",
    "source_urls": ["https://www.heygen.com/", "https://runwayml.com/", "https://www.synthesia.io/"],
    "script_provider": "template",
    "voice_provider": "placeholder",
    "brand_theme": "neon",
    "avatar_enabled": true,
    "avatar_position": "bottom_left",
    "burn_subtitles": true
  }'
```

`style: "ai_news_avatar"` строит ролик в формате AI-ведущего: крупный хук, аватар на весь экран, аватар в углу поверх демонстрации экрана, AI b-roll, доказательные вставки и финальный CTA.

### 2. Запустить генерацию как job

```bash
curl -X POST http://localhost:8000/projects/<project_id>/jobs/generate_all
```

Для повторной фоновой проверки HeyGen-аватаров можно запускать отдельную задачу:

```bash
curl -X POST http://localhost:8000/projects/<project_id>/jobs/sync_avatar
```

Или короткий alias:

```bash
curl -X POST http://localhost:8000/projects/<project_id>/generate-all-queued
```

### 3. Проверять job progress

```bash
curl http://localhost:8000/jobs/<job_id>
```

Отменить или повторить job:

```bash
curl -X POST http://localhost:8000/jobs/<job_id>/cancel
curl -X POST http://localhost:8000/jobs/<job_id>/retry
```

Ответ:

```json
{
  "id": "job_...",
  "project_id": "project_...",
  "type": "generate_all",
  "status": "running",
  "progress": 66,
  "current_step": "finished_generate_slides",
  "error": null
}
```

### 4. Получить результат

```bash
curl http://localhost:8000/projects/<project_id>/result
```

## Синхронный pipeline

Для локального теста можно по-прежнему запускать всё одним запросом:

```bash
curl -X POST http://localhost:8000/projects/<project_id>/generate-all
```

Или пошагово:

```bash
curl -X POST http://localhost:8000/projects/<project_id>/generate-script
curl -X POST http://localhost:8000/projects/<project_id>/collect-sources
curl -X POST http://localhost:8000/projects/<project_id>/generate-voice
curl -X POST http://localhost:8000/projects/<project_id>/generate-slides
curl -X POST http://localhost:8000/projects/<project_id>/prepare-avatar
curl -X POST http://localhost:8000/projects/<project_id>/sync-avatar
curl -X POST http://localhost:8000/projects/<project_id>/render
```

## Редактор сцен

Вставить сцену:

```bash
curl -X POST http://localhost:8000/projects/<project_id>/scenes \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "Новая сцена",
    "narration": "Текст озвучки для новой сцены.",
    "duration_sec": 12,
    "order": 2,
    "visual_type": "screen_demo"
  }'
```

Обновить сцену:

```bash
curl -X PATCH http://localhost:8000/projects/<project_id>/scenes/<scene_id> \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "Новый хук",
    "on_screen_text": "AI-видео: что выбрать",
    "duration_sec": 20,
    "visual_prompt": "neon SaaS explainer slide with huge readable title"
  }'
```

Переставить сцены:

```bash
curl -X POST http://localhost:8000/projects/<project_id>/scenes/reorder \
  -H 'Content-Type: application/json' \
  -d '{"scene_ids": ["scene_...", "scene_..."]}'
```

Удалить сцену:

```bash
curl -X DELETE http://localhost:8000/projects/<project_id>/scenes/<scene_id>
```

После правки можно перегенерировать один слайд:

```bash
curl -X POST http://localhost:8000/projects/<project_id>/scenes/<scene_id>/regenerate-slide
```

Для avatar-сцен можно повторить только HeyGen-задачу выбранной сцены:

```bash
curl -X POST http://localhost:8000/projects/<project_id>/scenes/<scene_id>/retry-avatar
```

## Подключение OpenAI LLM/TTS

```bash
cd backend
export OPENAI_API_KEY="sk-..."
export DEFAULT_SCRIPT_PROVIDER=openai
export DEFAULT_VOICE_PROVIDER=openai
export OPENAI_MODEL=gpt-4.1-mini
export OPENAI_TTS_MODEL=gpt-4o-mini-tts
export OPENAI_TTS_VOICE=alloy
export ENABLE_MODEL_IMAGES=true
export OPENAI_IMAGE_MODEL=gpt-image-1
export OPENAI_IMAGE_SIZE=1536x1024
uvicorn app.main:app --reload
```

Можно включать провайдеры на уровне проекта:

```json
{
  "script_provider": "openai",
  "voice_provider": "openai",
  "voice_id": "alloy"
}
```

Если ключ не задан или OpenAI недоступен, backend не падает: он пишет warning и использует template/placeholder/offline visual fallback.

## Подключение HeyGen avatar provider

`prepare-avatar` готовит аватарные сцены для HeyGen. Без ключей он создаёт `avatar_manifest.json` с placeholder-статусами, а с ключами отправляет каждую сцену `avatar_fullscreen`, `avatar_pip`, `screen_demo` и `cta` в HeyGen.

```bash
cd backend
export HEYGEN_API_KEY="..."
export HEYGEN_AVATAR_ID="..."
export HEYGEN_VOICE_ID="..." # опционально
export HEYGEN_RESOLUTION=1080p
export HEYGEN_OUTPUT_FORMAT=mp4
export HEYGEN_REMOVE_BACKGROUND=true
export HEYGEN_ENABLE_MOTION_PROMPT=false
export HEYGEN_POLL_SECONDS=0
uvicorn app.main:app --reload
```

Если HeyGen вернул готовый `video_url`, backend попытается скачать MP4 в `assets/avatar`. При наличии локального `avatar_video_path` финальный render использует avatar-video compositor: `avatar_fullscreen` идёт на весь экран, а `avatar_pip`, `screen_demo` и `cta` накладываются поверх PNG-визуала как PIP. Если MP4 ещё не готов, остаётся slideshow fallback.
`HEYGEN_ENABLE_MOTION_PROMPT` по умолчанию выключен, потому что HeyGen принимает motion prompt не для всех avatar engine/avatar types.

После первичной отправки можно вызывать `POST /projects/<project_id>/sync-avatar`: backend проверит статусы уже созданных HeyGen-задач и скачает готовые MP4, не создавая новые jobs. В production-режиме удобнее запускать это через очередь: `POST /projects/<project_id>/jobs/sync_avatar`. Если конкретная сцена неудачная или текст был изменён, `POST /projects/<project_id>/scenes/<scene_id>/retry-avatar` сбросит старый `avatar_video_id/status/url/path` и отправит в HeyGen только эту сцену.

## Реальные скриншоты сайтов

По умолчанию:

```text
ENABLE_BROWSER_SCREENSHOTS=false
```

Это значит, что приложение рисует offline preview-карточки. Чтобы попробовать настоящие скриншоты:

```bash
cd backend
pip install playwright
playwright install chromium
ENABLE_BROWSER_SCREENSHOTS=true uvicorn app.main:app --reload
```

Даже при включённых браузерных скриншотах пользователь должен проверять условия сайта, brand guidelines и корректность использования в обзоре.

Защита source URLs включена по умолчанию: localhost, private networks, link-local адреса и plain HTTP блокируются. Для локальных экспериментов можно явно задать `ALLOW_UNSAFE_HTTP_SOURCES=true` и `ALLOW_PRIVATE_SOURCE_URLS=true`.

## Мобильное приложение

В папке `mobile/` лежит минимальный Expo-скелет. Он вызывает API backend, создаёт проект, запускает `generate_all` как job, показывает progress, источники, warnings и ссылки на результат.

```bash
cd mobile
npm install
npm start
```

Перед запуском backend должен работать на `http://localhost:8000`. На реальном телефоне задайте `EXPO_PUBLIC_API_BASE_URL=http://<LAN_IP>:8000`; если backend использует `API_KEY`, задайте `EXPO_PUBLIC_API_KEY`.

## Тесты

```bash
cd backend
python -m pytest -q
```

Тесты не требуют системного FFmpeg: render использует bundled fallback из `imageio-ffmpeg`, если `FFMPEG_BIN` не найден.

Полная локальная проверка:

```bash
cd backend
python -c "import app.main"
python -m pytest -q

cd ../mobile
npm run check
npm run audit:prod
```

`npm run check` не требует сети и запускает TypeScript. `npm run audit:prod` требует доступ к npm registry. В репозитории есть GitHub Actions workflow `.github/workflows/ci.yml`, который выполняет backend import/tests и mobile audit/typecheck.

## Что подключать следующим шагом

1. Redis/BullMQ/Celery/Temporal вместо локальной job-системы.
2. Улучшенный video compositor: прозрачный фон, маски, motion transitions и точное lipsync-таймирование.
3. Voice consent flow и voice profiles.
4. Полноценный Playwright worker и поиск official websites.
5. Remotion-шаблоны вместо простых Pillow-слайдов.
6. S3/R2-хранилище вместо локальных файлов.
7. Пользовательская авторизация, тарифы и лимиты.
