# Changelog

## v0.4

Добавлено:

- локальная файловая job-система: `ProjectJob`, `JobStore`, `JobRunner`;
- `JobType`: `generate_script`, `collect_sources`, `generate_slides`, `generate_voice`, `prepare_avatar`, `render`, `generate_all`;
- `JobStatus`: `queued`, `running`, `completed`, `failed`;
- endpoint `POST /projects/{id}/jobs/{job_type}`;
- alias `POST /projects/{id}/generate-all-queued`;
- endpoint `GET /jobs/{job_id}`;
- endpoint `GET /projects/{id}/jobs`;
- progress polling для мобильного клиента;
- настройки `RUN_JOBS_INLINE` и `JOB_WORKERS`;
- endpoint `POST /projects/{id}/duplicate`;
- endpoint `DELETE /projects/{id}`;
- вставка сцен: `POST /projects/{id}/scenes`;
- удаление сцен: `DELETE /projects/{id}/scenes/{scene_id}`;
- перестановка сцен: `POST /projects/{id}/scenes/reorder`;
- очистка stale `visual_path`/`audio_path` после правки сцены;
- `run_job_demo.py`;
- обновлённый Expo mobile stub с job progress polling;
- дополнительные tests для job runner, duplicate project, insert/delete/reorder scenes.

Проверено:

- `python -m pytest -q` → 9 tests passed;
- `DATA_DIR=/tmp/... python run_demo.py` → создаёт MP4, SRT/VTT, thumbnail, metadata, quality report и result package;
- `DATA_DIR=/tmp/... RUN_JOBS_INLINE=true python run_job_demo.py` → выполняет generate_all через job layer.

## v0.3

Добавлено:

- `script_provider`: `template` или `openai`;
- `voice_provider`: `placeholder` или `openai`;
- optional OpenAI LLM adapter для генерации сцен;
- optional OpenAI TTS adapter для WAV-озвучки;
- безопасный fallback на template/placeholder при отсутствии `OPENAI_API_KEY`;
- `/providers` endpoint для проверки доступных провайдеров;
- новые настройки проекта: `brand_theme`, `voice_id`, `burn_subtitles`;
- `voice_manifest.json`;
- `thumbnail.png`;
- `title_options.txt`;
- `youtube_metadata.json`;
- `quality_report.json`;
- расширенный `result_package.zip`;
- новые tests для fallback LLM/TTS;
- обновлённый Expo mobile stub с переключателями LLM/TTS/subtitles.

Проверено:

- `python -m pytest -q` → 6 tests passed;
- `DATA_DIR=/tmp/... python run_demo.py` → создаёт MP4, SRT/VTT, thumbnail, metadata, quality report и result package.

## v0.2

Добавлено:

- SourceService для безопасных источников;
- `source_urls` в проекте;
- curated official websites по темам AI/video/automation/YouTube/Notion;
- ScreenshotService с offline fallback-карточками;
- опциональный Playwright screenshot mode;
- `collect-sources` endpoint;
- сцены с типами `ai_slide`, `screenshot`, `table`, `diagram`;
- привязка источников к screenshot-сценам;
- экспорт `storyboard.json`;
- экспорт `thumbnail_prompt.txt`;
- экспорт `captions.vtt`;
- экспорт `result_package.zip`;
- PATCH endpoint для редактирования сцен;
- endpoint для перегенерации одного слайда;
- дополнительные tests;
- обновлённый Expo mobile stub.

Проверено:

- `python -m pytest -q` → 4 tests passed;
- `DATA_DIR=/tmp/... python run_demo.py` → создаёт MP4 и result package.

## v0.1

- базовый pipeline: topic → script → slides → placeholder voice → MP4;
- FastAPI backend;
- локальное файловое хранилище проектов;
- compliance guardrail;
- Expo mobile stub.
