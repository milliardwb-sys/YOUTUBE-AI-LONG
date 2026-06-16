# ЮТУБ АИ ЛОНГ: описание проекта

`ЮТУБ АИ ЛОНГ` — MVP-платформа для генерации длинных YouTube-видео по теме. Текущая версия является рабочим техническим каркасом: она умеет принять тему ролика, создать структуру сцен, подобрать безопасные визуальные источники, сгенерировать слайды, сделать озвучку-заглушку или OpenAI TTS, собрать MP4 через FFmpeg и подготовить YouTube-пакет с метаданными.

Это не финальный SaaS-продукт. Архитектура специально сделана так, чтобы запускаться локально без платных AI-ключей, браузера и внешнего поиска. Production-слои подключаются постепенно: база данных, очередь, объектное хранилище, авторизация, биллинг, реальные avatar/voice/search/render провайдеры.

## Главная задача

Превратить простую идею ролика в набор готовых артефактов:

```text
тема
  -> проект
  -> job queue
  -> сценарий
  -> источники
  -> голос
  -> слайды
  -> avatar placeholder
  -> MP4
  -> YouTube metadata/export package
```

## Из чего состоит проект

- `backend/` — FastAPI backend, pipeline генерации, локальное файловое хранилище, job runner, render/export.
- `mobile/` — Expo/React Native MVP-клиент для запуска генерации и просмотра прогресса.
- `docs/` — API, архитектура, roadmap и это описание проекта.
- `docker-compose.yml` и `backend/Dockerfile` — production-like запуск backend в контейнере.
- `os-sota-*` — заготовки интеграции с OS SOTA командным центром.

## Как работает backend

Backend запускается как FastAPI API. Основные endpoint-группы:

- `/health`, `/ready`, `/diagnostics` — диагностика.
- `/providers` — доступные AI/render/source режимы.
- `/projects` — создание, чтение, обновление и удаление проектов.
- `/projects/{id}/jobs/{job_type}` — запуск долгих задач.
- `/jobs/{job_id}` — polling прогресса.
- `/jobs/{job_id}/events` — история событий job для диагностики и UI.
- `/jobs/{job_id}/cancel` — кооперативная отмена queued/running job.
- `/jobs/{job_id}/retry` — повторный запуск завершённой, failed или cancelled job.
- `/projects/{id}/scenes` — ручное редактирование сцен.
- `/projects/{id}/result` — ссылки на итоговые артефакты.
- `/files/{path}` — контролируемая выдача файлов из `DATA_DIR`.

В non-local окружениях приватные endpoints требуют `API_KEY`. Если `APP_ENV=production` и ключ не задан, backend возвращает `403` для приватных routes.

## Pipeline генерации

1. `ScriptService` создаёт сцены.
   - По умолчанию используется template generator.
   - Если выбран `script_provider=openai`, backend пробует OpenAI LLM.
   - Если OpenAI недоступен, pipeline не падает, а возвращается к template fallback.

2. `SourceService` собирает источники.
   - Берёт URL, которые указал пользователь.
   - Добавляет curated official websites по ключевым словам темы.
   - Блокирует localhost/private/plain HTTP по умолчанию.

3. `ScreenshotService` создаёт визуальные референсы.
   - По умолчанию рисует offline fallback-карточки.
   - При `ENABLE_BROWSER_SCREENSHOTS=true` пробует Playwright screenshots.

4. `VoiceService` создаёт audio.
   - По умолчанию пишет WAV-заглушки.
   - При `voice_provider=openai` пробует OpenAI TTS.
   - Пишет `voice_manifest.json`, SRT и VTT.

5. `VisualService` рисует PNG-слайды.
   - Поддерживает `ai_slide`, `screenshot`, `table`, `diagram`.
   - Использует Pillow.

6. `AvatarService` пока является placeholder.
   - Реальные HeyGen/D-ID/Tavus ещё не подключены.

7. `RenderService` собирает MP4.
   - Использует FFmpeg.
   - Если системный FFmpeg недоступен, пробует `imageio-ffmpeg`.
   - Создаёт YouTube metadata, thumbnail, quality report и zip package.

## Как работает mobile-клиент

Mobile-клиент — минимальный Expo-интерфейс:

- ввод темы;
- переключатели official sources, LLM script, TTS voice, burned subtitles;
- создание проекта;
- запуск `generate_all` как backend job;
- polling `/jobs/{job_id}`;
- возможность backend-отмены и retry job через API;
- отображение статуса, прогресса, warnings, сцен, источников и ссылок на результат.

На физическом телефоне backend должен быть доступен по LAN IP:

```text
EXPO_PUBLIC_API_BASE_URL=http://<LAN_IP>:8000
EXPO_PUBLIC_API_KEY=<API_KEY если backend защищён>
```

## Интеграции

### OpenAI

Используется опционально:

- LLM сценарист через `OPENAI_MODEL`.
- TTS через `OPENAI_TTS_MODEL` и `OPENAI_TTS_VOICE`.

Env:

```text
OPENAI_API_KEY=
DEFAULT_SCRIPT_PROVIDER=openai
DEFAULT_VOICE_PROVIDER=openai
```

Без ключа backend работает через template/placeholder fallback.

### FFmpeg

Используется для финального MP4 render. В Docker image установлен системный `ffmpeg`. Локально backend также может использовать bundled fallback из `imageio-ffmpeg`.

### Playwright

Опционален для реальных screenshots сайтов. По умолчанию выключен, чтобы MVP запускался без браузера.

Env:

```text
ENABLE_BROWSER_SCREENSHOTS=true
```

Нужно дополнительно установить Playwright и Chromium.

### OS SOTA

В корне есть JS/Python клиенты OS SOTA:

- `os-sota-core-client.mjs`
- `os_sota_core_client.py`
- `os-sota-auto-hooks.mjs`
- smoke tests

Они предназначены для безопасной отправки событий, метрик, ошибок, AI usage, payments/tasks/documents в внешний командный центр. Если OS SOTA недоступен, события можно складывать в локальную очередь `.os-sota-sync-queue.jsonl`.

### Docker / Compose

Backend можно запускать через Docker Compose:

```bash
cp backend/.env.production.example backend/.env.production
docker compose up --build
```

Для проверки:

```bash
curl http://127.0.0.1:8000/ready
curl -H "X-API-Key: <API_KEY>" http://127.0.0.1:8000/projects
```

## Что сейчас готово

- Backend MVP.
- Mobile MVP.
- Job progress polling.
- Job cancel/retry endpoints.
- Job events/history в JSON job-файлах.
- Template сценарии.
- OpenAI LLM/TTS adapters.
- Safe source URL validation.
- Fallback visual cards.
- Pillow slides.
- FFmpeg MP4 render.
- YouTube metadata/export package.
- API key protection.
- Docker/Compose backend scaffold.
- GitHub Actions CI.

## Что ещё не production

- Нет PostgreSQL.
- Нет Redis/Celery/RQ/Temporal.
- Нет user accounts и project ownership.
- Нет billing/limits.
- Нет real avatar provider.
- Нет voice consent flow.
- Нет real search/research provider.
- Нет Remotion-quality render templates.
- Нет полноценного scene editor UI.
- Нет observability: metrics/traces/job dashboards.

## Ближайший путь до готовности

1. Закрыть backend как стабильный API: auth, rate limits, structured errors, logs.
2. Заменить JSON storage на PostgreSQL.
3. Заменить local job runner на Redis/Celery/RQ/Temporal.
4. Перенести файлы в S3/R2 и выдавать signed URLs.
5. Сделать полноценный editor для сцен и источников.
6. Подключить production render stack на Remotion.
7. Подключить avatar/voice providers с consent flow.
8. Добавить billing, лимиты, cost tracking и admin panel.
