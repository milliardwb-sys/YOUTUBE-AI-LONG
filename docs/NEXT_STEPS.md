# Следующие задачи разработки после v0.4

## Milestone 1 — production queue

В v0.4 уже есть локальная job-система. Следующий шаг — заменить её production-инфраструктурой:

- Redis + BullMQ/Celery/RQ или Temporal.
- Retry policy.
- Progress events через WebSocket/SSE.
- Cancel/retry job endpoints.
- Отдельные workers: research, screenshot, voice, render.
- Per-user concurrency limits.
- Cost tracking по LLM/TTS/render минутам.

## Milestone 2 — AI-сценарист production-grade

- Улучшить `OpenAILLMProvider` JSON schema/validation.
- Добавить retry/repair JSON-ответов.
- Добавить фактологический research context до генерации сценария.
- Добавить стили: обзор, туториал, топ, тренд, продающий ролик.
- Генерировать title, description, CTA и chapters через LLM.
- Добавить human review экран для сценария.

## Milestone 3 — настоящие источники

- Подключить SearchProvider для поиска официальных сайтов.
- Добавить проверку canonical URL и brand domain.
- Добавить страницы `pricing/features/docs` для каждой платформы.
- Добавить confidence-score источника.
- Добавить ручное утверждение источников пользователем.
- Добавить brand/legal notes для каждого source.

## Milestone 4 — screenshot worker

- Вынести Playwright в отдельный worker.
- Добавить browser pool.
- Добавить cookie-banner resolver.
- Добавить full-page / viewport / element screenshot.
- Добавить blur случайных персональных данных.
- Добавить crop/highlight/zoom.
- Сохранять raw screenshot + processed screenshot отдельно.

## Milestone 5 — голос и voice clone

- Добавить VoiceProfile model.
- Добавить consent recording storage.
- Добавить провайдеры OpenAI/ElevenLabs/Azure.
- Добавить нормализацию громкости.
- Добавить паузы и SSML-like controls.
- Добавить предупреждения, если используется синтетический голос.
- Отдельно реализовать юридический consent flow для пользовательского голоса.

## Milestone 6 — аватар

- Реализовать `AvatarProvider` adapter.
- Начать с HeyGen/D-ID/Tavus.
- Добавить avatar profile, avatar id, consent status.
- Добавить overlay position/shape.
- Поддержать transparent video или background removal.
- Добавить скрытие аватара на selected scenes.
- Синхронизировать talking-head с финальным voiceover.

## Milestone 7 — визуальный редактор

- Экран сценария.
- Экран источников.
- Экран визуалов.
- Замена источника для сцены.
- Перегенерация отдельного слайда.
- Предпросмотр результата.
- Ручная правка титров.
- Возможность скрыть/показать аватар на сцене.
- Drag-and-drop reorder в мобильном/веб UI.

## Milestone 8 — рендер production качества

- Перевести простые Pillow-слайды на Remotion templates.
- Добавить анимации, zoom, highlights, transitions.
- Добавить burned-in subtitles при `burn_subtitles=true`.
- Добавить 4K export для Pro-тарифа.
- Добавить render presets: YouTube 16:9, Shorts 9:16, square 1:1.
- Добавить preview render в низком разрешении.

## Milestone 9 — infrastructure

- PostgreSQL вместо JSON-файлов.
- S3/R2 storage.
- Signed URLs.
- Авторизация: MVP foundation уже есть через `ENABLE_USER_AUTH`, bearer sessions, `owner_id` у projects/jobs и file access checks. Production-доработки: OIDC/managed auth, organizations, roles, audit logs, session revocation UI.
- Тарифы и лимиты.
- Admin panel.
- Observability: logs, traces, job retries.
- Billing events по рендер-минутам и AI-cost.
