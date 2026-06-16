from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.models import JobStatus, JobType, ProjectCreate, ProjectStatus, SceneCreate, ScenePatch, SceneReorder, ScriptProviderName, VisualMode, VoiceProviderName
from app.pipeline import VideoPipeline
from app.services.avatar_service import AvatarService
from app.services.compliance_service import ComplianceService
from app.services.job_service import JobNotCancellableError, JobRunner, JobStore
from app.services.render_service import RenderService
from app.services.script_service import ScriptService
from app.services.source_service import SourceService
from app.services.visual_service import VisualService
from app.services.voice_service import VoiceService
from app.storage import ProjectStore
from app.utils.security import InvalidIdentifierError


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        data_dir=tmp_path,
        public_base_url="http://test",
        ffmpeg_bin="ffmpeg",
        render_width=1920,
        render_height=1080,
        render_fps=15,
        enable_browser_screenshots=False,
        browser_timeout_ms=1000,
        default_script_provider="template",
        default_voice_provider="placeholder",
        openai_api_key=None,
        openai_model="gpt-4.1-mini",
        openai_temperature=0.55,
        openai_tts_model="gpt-4o-mini-tts",
        openai_tts_voice="alloy",
        max_openai_tts_chars=3800,
        burn_subtitles_by_default=False,
        run_jobs_inline=True,
        job_workers=1,
        api_key=None,
        rate_limit_requests_per_minute=0,
        cors_origins=["http://localhost:19006"],
        allow_unsafe_http_sources=False,
        allow_private_source_urls=False,
        cleanup_retention_days=14,
    )


def make_pipeline(settings: Settings, store: ProjectStore) -> VideoPipeline:
    return VideoPipeline(
        store=store,
        compliance=ComplianceService(),
        script=ScriptService(settings),
        sources=SourceService(settings),
        visuals=VisualService(settings),
        voice=VoiceService(settings),
        avatar=AvatarService(),
        render=RenderService(settings),
    )


def test_script_generation(tmp_path):
    settings = make_settings(tmp_path)
    store = ProjectStore(settings)
    project = store.create_project(
        ProjectCreate(topic="Тестовый ролик про AI-видео", duration_minutes=1)
    )
    pipeline = make_pipeline(settings, store)
    result = pipeline.generate_script(project.id)
    assert result.scenes
    assert result.status == "script_ready"


def test_official_sources_and_slides(tmp_path):
    settings = make_settings(tmp_path)
    store = ProjectStore(settings)
    project = store.create_project(
        ProjectCreate(
            topic="5 AI-сервисов для создания видео",
            duration_minutes=1,
            visual_mode=VisualMode.official_sites_plus_ai,
            source_urls=["https://www.heygen.com/"],
        )
    )
    pipeline = make_pipeline(settings, store)
    result = pipeline.generate_script(project.id)
    result = pipeline.collect_sources(result.id)
    result = pipeline.generate_slides(result.id)

    assert result.sources
    assert any(scene.visual_type == "screenshot" for scene in result.scenes)
    assert all(Path(scene.visual_path).exists() for scene in result.scenes)
    assert all(source.screenshot_path and Path(source.screenshot_path).exists() for source in result.sources)


def test_scene_patch_recalculates_timings(tmp_path):
    settings = make_settings(tmp_path)
    store = ProjectStore(settings)
    project = store.create_project(ProjectCreate(topic="Тестовый ролик про монтаж", duration_minutes=1))
    pipeline = make_pipeline(settings, store)
    project = pipeline.generate_script(project.id)
    first_scene = project.scenes[0]
    updated = store.patch_scene(project.id, first_scene.id, ScenePatch(duration_sec=20, title="Новый хук"))

    assert updated.scenes[0].duration_sec == 20
    assert updated.scenes[0].title == "Новый хук"
    assert updated.scenes[1].start_sec == 20


def test_compliance_blocks_youtube_source(tmp_path):
    settings = make_settings(tmp_path)
    store = ProjectStore(settings)
    project = store.create_project(
        ProjectCreate(
            topic="Разбор сервиса",
            duration_minutes=1,
            visual_mode=VisualMode.official_sites_plus_ai,
            source_urls=["https://www.youtube.com/watch?v=test"],
        )
    )
    pipeline = make_pipeline(settings, store)
    result = pipeline.generate_all(project.id)

    assert result.status == "failed"
    assert "YouTube" in (result.error or "")


def test_llm_provider_without_key_falls_back_to_template(tmp_path):
    settings = make_settings(tmp_path)
    store = ProjectStore(settings)
    project = store.create_project(
        ProjectCreate(
            topic="Тестовый ролик про AI-сценарист",
            duration_minutes=1,
            script_provider=ScriptProviderName.openai,
        )
    )
    pipeline = make_pipeline(settings, store)
    result = pipeline.generate_script(project.id)

    assert result.status == "script_ready"
    assert result.scenes
    assert any("LLM provider failed" in warning for warning in result.result.warnings)


def test_tts_provider_without_key_falls_back_to_placeholder(tmp_path):
    settings = make_settings(tmp_path)
    store = ProjectStore(settings)
    project = store.create_project(
        ProjectCreate(
            topic="Тестовый ролик про голос",
            duration_minutes=1,
            voice_provider=VoiceProviderName.openai,
        )
    )
    pipeline = make_pipeline(settings, store)
    result = pipeline.generate_script(project.id)
    result = pipeline.generate_voice(result.id)

    assert result.status == "voice_ready"
    assert result.result.voice_manifest_path
    assert all(scene.audio_path and Path(scene.audio_path).exists() for scene in result.scenes)
    assert any("TTS provider failed" in warning for warning in result.result.warnings)


def test_scene_insert_delete_and_reorder(tmp_path):
    settings = make_settings(tmp_path)
    store = ProjectStore(settings)
    project = store.create_project(ProjectCreate(topic="Тестовый ролик про редактор сцен", duration_minutes=1))
    pipeline = make_pipeline(settings, store)
    project = pipeline.generate_script(project.id)
    original_count = len(project.scenes)

    inserted = store.insert_scene(
        project.id,
        SceneCreate(title="Ручная вставка", duration_sec=10, order=2),
    )
    assert len(inserted.scenes) == original_count + 1
    assert inserted.scenes[1].title == "Ручная вставка"
    assert inserted.scenes[2].start_sec == inserted.scenes[0].duration_sec + 10

    reversed_ids = [scene.id for scene in reversed(inserted.scenes)]
    reordered = store.reorder_scenes(project.id, SceneReorder(scene_ids=reversed_ids))
    assert reordered.scenes[0].id == reversed_ids[0]
    assert [scene.order for scene in reordered.scenes] == list(range(1, len(reordered.scenes) + 1))

    deleted = store.delete_scene(project.id, reordered.scenes[0].id)
    assert len(deleted.scenes) == original_count


def test_duplicate_project_resets_outputs(tmp_path):
    settings = make_settings(tmp_path)
    store = ProjectStore(settings)
    project = store.create_project(ProjectCreate(topic="Тестовый ролик для копирования", duration_minutes=1))
    pipeline = make_pipeline(settings, store)
    project = pipeline.generate_script(project.id)

    duplicate = store.duplicate_project(project.id)
    assert duplicate.id != project.id
    assert duplicate.topic.endswith("— копия")
    assert duplicate.scenes == []
    assert duplicate.sources == []
    assert duplicate.status == "draft"


def test_project_and_job_stats(tmp_path):
    settings = make_settings(tmp_path)
    store = ProjectStore(settings)
    job_store = JobStore(settings)
    project = store.create_project(ProjectCreate(topic="Тестовый проект для статистики"))
    job = job_store.create(project.id, JobType.generate_script)
    job.mark_cancelled("not needed")
    job_store.save(job)

    project_stats = store.stats()
    job_stats = job_store.stats()

    assert project_stats["project_count"] == 1
    assert project_stats["projects_by_status"]["draft"] == 1
    assert project_stats["storage_files"] >= 2
    assert job_stats["job_count"] == 1
    assert job_stats["terminal_jobs"] == 1
    assert job_stats["jobs_by_status"]["cancelled"] == 1
    assert job_stats["jobs_by_type"]["generate_script"] == 1


def test_inline_job_runner_generate_all(tmp_path):
    settings = make_settings(tmp_path)
    store = ProjectStore(settings)
    pipeline = make_pipeline(settings, store)
    job_store = JobStore(settings)
    runner = JobRunner(settings, pipeline, job_store)
    project = store.create_project(
        ProjectCreate(
            topic="Тестовый job-pipeline для AI-видео",
            duration_minutes=1,
            visual_mode=VisualMode.ai_slides_only,
        )
    )

    job = runner.start(project.id, JobType.generate_all)
    saved_job = job_store.get(job.id)
    generated = store.get(project.id)

    if RenderService(settings).resolve_ffmpeg_bin():
        assert saved_job.status == JobStatus.completed
        assert saved_job.progress == 100
        assert generated.result.final_video_path
        assert Path(generated.result.final_video_path).exists()
        with ZipFile(generated.result.export_package_path) as archive:
            assert "final.mp4" in archive.namelist()
    else:
        assert saved_job.status == JobStatus.failed
        assert "FFmpeg" in (saved_job.error or "")
    assert generated.status in {"completed", "failed"}
    assert generated.scenes
    assert generated.result.export_package_path
    assert saved_job.events
    assert saved_job.events[0]["event"] == "queued"
    assert any(event["event"] == "progress" for event in saved_job.events)


def test_render_service_resolves_ffmpeg_binary(tmp_path):
    settings = make_settings(tmp_path)
    resolver = RenderService(settings)
    assert resolver.resolve_ffmpeg_bin()


def test_get_settings_parses_openai_temperature(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPENAI_TEMPERATURE", "0.2")
    settings = get_settings()

    assert settings.openai_temperature == 0.2


def test_get_settings_uses_default_for_invalid_openai_temperature(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPENAI_TEMPERATURE", "not-a-number")
    settings = get_settings()

    assert settings.openai_temperature == 0.55


def test_get_settings_parses_rate_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "12")
    settings = get_settings()

    assert settings.rate_limit_requests_per_minute == 12


def test_api_import_and_delete_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUN_JOBS_INLINE", "true")
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "local")
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    health = client.get("/health")
    assert health.status_code == 200
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["ffmpeg_available"] is True
    created = client.post("/projects", json={"topic": "Тестовый API smoke проект"})
    assert created.status_code == 200
    project_id = created.json()["id"]
    deleted = client.delete(f"/projects/{project_id}")
    assert deleted.status_code == 204


def test_api_key_protects_non_public_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("API_KEY", "secret")
    monkeypatch.setenv("APP_ENV", "production")
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    assert client.get("/projects").status_code == 401
    assert client.get("/diagnostics").status_code == 401
    assert client.get("/projects", headers={"x-api-key": "secret"}).status_code == 200
    assert client.get("/diagnostics", headers={"x-api-key": "secret"}).status_code == 200


def test_api_stats_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    created = client.post("/projects", json={"topic": "Тестовый API stats проект"})
    assert created.status_code == 200
    response = client.get("/stats")

    assert response.status_code == 200
    payload = response.json()
    assert payload["storage"]["project_count"] == 1
    assert payload["jobs"]["job_count"] == 0


def test_api_rate_limit_returns_429(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "2")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    first = client.get("/health")
    second = client.get("/health")
    third = client.get("/health")

    assert first.status_code == 200
    assert first.headers["x-ratelimit-limit"] == "2"
    assert second.status_code == 200
    assert third.status_code == 429


def test_production_requires_api_key_for_private_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    assert client.get("/health").status_code == 200
    assert client.get("/providers").status_code == 200
    response = client.get("/projects")

    assert response.status_code == 403
    assert "API_KEY" in response.json()["detail"]


def test_api_render_precondition_returns_409(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "local")
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    created = client.post("/projects", json={"topic": "Тестовый render precondition проект"})
    project_id = created.json()["id"]
    response = client.post(f"/projects/{project_id}/render")

    assert response.status_code == 409
    assert response.json()["detail"]["current_step"] == "precondition_failed"


def test_api_cancel_and_retry_job(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUN_JOBS_INLINE", "true")
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    created = client.post("/projects", json={"topic": "Тестовый API проект для cancel retry"})
    project_id = created.json()["id"]
    project = main.store.get(project_id)
    project.status = ProjectStatus.queued
    main.store.save(project)
    job = main.job_store.create(project_id, JobType.render)

    cancelled = client.post(f"/jobs/{job.id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    retried = client.post(f"/jobs/{job.id}/retry")
    assert retried.status_code == 200
    assert retried.json()["id"] != job.id
    assert retried.json()["status"] == "failed"

    cancel_again = client.post(f"/jobs/{job.id}/cancel")
    assert cancel_again.status_code == 409

    events = client.get(f"/jobs/{job.id}/events")
    assert events.status_code == 200
    assert any(event["event"] == "cancelled" for event in events.json())


def test_files_endpoint_blocks_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_ENV", "local")
    (tmp_path / "victim.txt").write_text("secret", encoding="utf-8")
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    response = client.get("/files/%2E%2E/victim.txt")

    assert response.status_code == 404


def test_project_store_blocks_path_traversal(tmp_path):
    settings = make_settings(tmp_path / "data")
    store = ProjectStore(settings)
    store.create_project(ProjectCreate(topic="Тестовый проект для path traversal"))
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "project.json").write_text("{}", encoding="utf-8")

    with pytest.raises(InvalidIdentifierError):
        store.delete_project("../victim")
    assert victim.exists()


def test_private_source_url_is_rejected():
    with pytest.raises(ValueError):
        ProjectCreate(topic="Тестовый проект с приватным URL", source_urls=["http://127.0.0.1:8000"])


def test_job_runner_deduplicates_active_project_jobs(tmp_path):
    settings = make_settings(tmp_path)
    settings = Settings(**{**settings.__dict__, "run_jobs_inline": False})
    store = ProjectStore(settings)
    pipeline = make_pipeline(settings, store)
    job_store = JobStore(settings)
    runner = JobRunner(settings, pipeline, job_store)
    project = store.create_project(ProjectCreate(topic="Тестовый проект для дедупликации jobs"))

    first = runner.start(project.id, JobType.generate_all)
    second = runner.start(project.id, JobType.generate_all)

    assert second.id == first.id


def test_job_runner_can_cancel_queued_job_and_retry(tmp_path):
    settings = make_settings(tmp_path)
    store = ProjectStore(settings)
    pipeline = make_pipeline(settings, store)
    job_store = JobStore(settings)
    runner = JobRunner(settings, pipeline, job_store)
    project = store.create_project(ProjectCreate(topic="Тестовый проект для отмены job"))
    project.status = ProjectStatus.queued
    store.save(project)
    job = job_store.create(project.id, JobType.render)

    cancelled = runner.cancel(job.id)

    assert cancelled.status == JobStatus.cancelled
    assert store.get(project.id).status == "cancelled"

    retried = runner.retry(job.id)

    assert retried.id != job.id
    assert retried.status == JobStatus.failed
    assert "Project has no scenes" in (retried.error or "")


def test_job_store_rejects_cancelling_terminal_job(tmp_path):
    settings = make_settings(tmp_path)
    store = ProjectStore(settings)
    project = store.create_project(ProjectCreate(topic="Тестовый проект для terminal job"))
    job_store = JobStore(settings)
    job = job_store.create(project.id, JobType.generate_script)
    job.mark_completed("completed")
    job_store.save(job)

    with pytest.raises(JobNotCancellableError):
        job_store.cancel(job.id)
