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
- безопасный fallback на шаблонный сценарий, если API-ключа нет или провайдер упал;
- безопасный `SourceService`: user URLs + curated official websites;
- `ScreenshotService` с офлайн fallback-карточками источников;
- опциональный браузерный screenshot-capture через Playwright;
- генератор 16:9 PNG-слайдов через Pillow;
- режимы слайдов: `ai_slide`, `screenshot`, `table`, `diagram`;
- генератор WAV-аудио-заглушек;
- опциональный OpenAI TTS-провайдер для озвучки;
- `voice_manifest.json` с информацией по аудио каждой сцены;
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
```

То есть архив можно запустить локально, получить слайды, аудио-заглушку и MP4. Если добавить `OPENAI_API_KEY`, можно включить `script_provider=openai` и `voice_provider=openai`.

Если задать `API_KEY`, все endpoints кроме `/health`, `/ready`, `/providers` и документации требуют заголовок `X-API-Key`. CORS настраивается через `CORS_ORIGINS`.

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

После старта:

```bash
curl http://127.0.0.1:8000/ready
curl -H "X-API-Key: <API_KEY>" http://127.0.0.1:8000/projects
```

`APP_ENV=production` без `API_KEY` заблокирует приватные endpoints. Если `API_KEY` задан, backend отклонит известные placeholder-значения и секреты короче 32 символов. `RENDER_TIMEOUT_SECONDS` ограничивает длительность FFmpeg-render, чтобы зависший render не занимал worker бесконечно. Данные проектов сохраняются в Docker volume `backend-projects`.

`MAX_REQUEST_BODY_BYTES` ограничивает размер входящего HTTP body по `Content-Length`. Превышение лимита возвращает `413`.

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
    "topic": "5 AI-сервисов для создания видео в 2026 году",
    "duration_minutes": 3,
    "style": "expert_review",
    "language": "ru",
    "audience": "создатели YouTube-каналов",
    "visual_mode": "official_sites_plus_ai",
    "source_urls": ["https://www.heygen.com/", "https://runwayml.com/"],
    "script_provider": "template",
    "voice_provider": "placeholder",
    "brand_theme": "neon",
    "avatar_enabled": false,
    "burn_subtitles": false
  }'
```

### 2. Запустить генерацию как job

```bash
curl -X POST http://localhost:8000/projects/<project_id>/jobs/generate_all
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
    "visual_type": "ai_slide"
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

## Подключение OpenAI LLM/TTS

```bash
cd backend
export OPENAI_API_KEY="sk-..."
export DEFAULT_SCRIPT_PROVIDER=openai
export DEFAULT_VOICE_PROVIDER=openai
export OPENAI_MODEL=gpt-4.1-mini
export OPENAI_TTS_MODEL=gpt-4o-mini-tts
export OPENAI_TTS_VOICE=alloy
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

Если ключ не задан или OpenAI недоступен, backend не падает: он пишет warning и использует template/placeholder fallback.

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
2. Реальный avatar-provider: HeyGen / D-ID / Tavus.
3. Voice consent flow и voice profiles.
4. Полноценный Playwright worker и поиск official websites.
5. Remotion-шаблоны вместо простых Pillow-слайдов.
6. S3/R2-хранилище вместо локальных файлов.
7. Пользовательская авторизация, тарифы и лимиты.
