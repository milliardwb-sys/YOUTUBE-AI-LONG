from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from app.config import ConfigurationError, Settings, get_settings
from app.models import JobStatus, JobType, ProjectCreate, ProjectStatus, SceneCreate, ScenePatch, SceneReorder, ScriptProviderName, UserCreate, UserSession, VisualMode, VoiceProviderName
from app.pipeline import VideoPipeline
from app.services.avatar_service import AvatarService
from app.services.auth_service import AuthService, SessionNotFoundError
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
        enable_user_auth=False,
        access_token_ttl_minutes=1440,
        rate_limit_requests_per_minute=0,
        cors_origins=["http://localhost:19006"],
        allow_unsafe_http_sources=False,
        allow_private_source_urls=False,
        cleanup_retention_days=14,
        render_timeout_seconds=1800,
        max_request_body_bytes=2_000_000,
        usage_max_projects_per_user=25,
        usage_max_active_jobs_per_user=2,
        usage_llm_job_cost_cents=1,
        usage_tts_cost_cents_per_minute=1,
        usage_render_cost_cents_per_minute=2,
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


def test_render_service_times_out_ffmpeg(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    settings = Settings(**{**settings.__dict__, "render_timeout_seconds": 1})
    renderer = RenderService(settings)

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0] if args else "ffmpeg", timeout=kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="timed out"):
        renderer._run(["ffmpeg", "-version"])


def test_render_export_package_skips_paths_outside_project_dir(tmp_path):
    settings = make_settings(tmp_path / "data")
    store = ProjectStore(settings)
    project = store.create_project(ProjectCreate(topic="Тестовый проект для безопасного export package"))
    project_dir = store.project_dir(project.id)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    inside = project_dir / "exports" / "sources.json"
    inside.parent.mkdir(parents=True, exist_ok=True)
    inside.write_text("{}", encoding="utf-8")
    project.result.description_path = str(outside)
    project.result.sources_path = str(inside)

    RenderService(settings)._create_export_package(project, project_dir)

    with ZipFile(project.result.export_package_path) as archive:
        names = archive.namelist()
    assert "outside.txt" not in names
    assert "sources.json" in names
    assert any("path escapes project directory" in warning for warning in project.result.warnings)


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


def test_get_settings_rejects_weak_production_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_KEY", "CHANGE_ME_TO_A_LONG_RANDOM_SECRET")

    with pytest.raises(ConfigurationError):
        get_settings()


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


def test_api_project_create_idempotency_key_replays_same_resource(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    headers = {"Idempotency-Key": "project-create-01"}
    payload = {"topic": "Retry safe API project creation"}
    first = client.post("/projects", json=payload, headers=headers)
    second = client.post("/projects", json=payload, headers=headers)
    conflict = client.post("/projects", json={"topic": "Different retry payload"}, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.headers["x-idempotent-replay"] == "false"
    assert second.headers["x-idempotent-replay"] == "true"
    assert conflict.status_code == 409


def test_api_rejects_invalid_idempotency_key(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    response = client.post(
        "/projects",
        json={"topic": "Project with invalid idempotency key"},
        headers={"Idempotency-Key": "bad key"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["status_code"] == 400


def test_api_list_projects_supports_pagination_headers(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    for index in range(3):
        response = client.post("/projects", json={"topic": f"Paginated API project {index}"})
        assert response.status_code == 200

    page = client.get("/projects?limit=2&offset=1")

    assert page.status_code == 200
    assert page.headers["x-total-count"] == "3"
    assert page.headers["x-limit"] == "2"
    assert page.headers["x-offset"] == "1"
    assert len(page.json()) == 2


def test_api_job_start_idempotency_key_replays_same_job(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUN_JOBS_INLINE", "true")
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    created = client.post("/projects", json={"topic": "Retry safe queued job project"})
    project_id = created.json()["id"]
    headers = {"Idempotency-Key": "job-start-01"}
    first = client.post(f"/projects/{project_id}/jobs/generate_script", headers=headers)
    second = client.post(f"/projects/{project_id}/jobs/generate_script", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.headers["x-idempotent-replay"] == "false"
    assert second.headers["x-idempotent-replay"] == "true"


def test_api_project_jobs_and_events_support_pagination_headers(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    created = client.post("/projects", json={"topic": "Paginated project jobs"})
    project_id = created.json()["id"]
    jobs = [main.job_store.create(project_id, JobType.generate_script) for _ in range(3)]
    job_with_events = jobs[0]
    job_with_events.add_event("step_one", "one", 10)
    job_with_events.add_event("step_two", "two", 20)
    job_with_events.add_event("step_three", "three", 30)
    main.job_store.save(job_with_events)

    jobs_page = client.get(f"/projects/{project_id}/jobs?limit=2&offset=1")
    events_page = client.get(f"/jobs/{job_with_events.id}/events?limit=2&offset=1")

    assert jobs_page.status_code == 200
    assert jobs_page.headers["x-total-count"] == "3"
    assert len(jobs_page.json()) == 2
    assert events_page.status_code == 200
    assert events_page.headers["x-total-count"] == "4"
    assert len(events_page.json()) == 2


def test_api_key_protects_non_public_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    api_key = "test-secret-value-with-more-than-32-chars"
    monkeypatch.setenv("API_KEY", api_key)
    monkeypatch.setenv("APP_ENV", "production")
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    assert client.get("/projects").status_code == 401
    assert client.get("/diagnostics").status_code == 401
    assert client.get("/projects", headers={"x-api-key": api_key}).status_code == 200
    assert client.get("/diagnostics", headers={"x-api-key": api_key}).status_code == 200


def test_user_auth_register_login_and_me(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ENABLE_USER_AUTH", "true")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    register = client.post(
        "/auth/register",
        json={"email": "Owner@example.com", "password": "strong-password", "name": "Owner"},
    )
    assert register.status_code == 200
    assert register.json()["user"]["email"] == "owner@example.com"
    assert register.json()["token_type"] == "bearer"

    login = client.post("/auth/login", json={"email": "owner@example.com", "password": "strong-password"})
    assert login.status_code == 200
    token = login.json()["access_token"]

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "owner@example.com"

    logout = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout.status_code == 200
    assert logout.json()["revoked"] is True
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_auth_service_revokes_and_cleans_expired_sessions(tmp_path):
    settings = make_settings(tmp_path)
    settings = Settings(**{**settings.__dict__, "enable_user_auth": True})
    auth = AuthService(settings)
    issued = auth.register(UserCreate(email="cleanup@example.com", password="strong-password"))

    assert auth.get_user_by_token(issued.access_token).email == "cleanup@example.com"
    assert auth.revoke_token(issued.access_token) is True
    with pytest.raises(SessionNotFoundError):
        auth.get_user_by_token(issued.access_token)

    user = auth.find_user_by_email("cleanup@example.com")
    assert user is not None
    expired = UserSession(
        user_id=user.id,
        token_hash="expired-session-token-hash",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    auth._save_session(expired)

    cleanup = auth.cleanup_expired_sessions()
    assert cleanup["removed_sessions"] == 1
    assert cleanup["skipped_sessions"] == 0


def test_user_auth_isolates_projects_jobs_and_files(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ENABLE_USER_AUTH", "true")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    alice = client.post(
        "/auth/register",
        json={"email": "alice@example.com", "password": "strong-password"},
    ).json()["access_token"]
    bob = client.post(
        "/auth/register",
        json={"email": "bob@example.com", "password": "strong-password"},
    ).json()["access_token"]
    alice_headers = {"Authorization": f"Bearer {alice}"}
    bob_headers = {"Authorization": f"Bearer {bob}"}

    missing_auth = client.get("/projects")
    assert missing_auth.status_code == 401

    created = client.post("/projects", json={"topic": "Auth isolated video project"}, headers=alice_headers)
    assert created.status_code == 200
    project_id = created.json()["id"]
    assert created.json()["owner_id"]

    assert client.get(f"/projects/{project_id}", headers=alice_headers).status_code == 200
    assert client.get(f"/projects/{project_id}", headers=bob_headers).status_code == 404
    assert client.get("/projects", headers=bob_headers).json() == []

    project_dir = main.store.project_dir(project_id)
    artifact = project_dir / "artifact.txt"
    artifact.write_text("private artifact", encoding="utf-8")
    alice_file = client.get(f"/files/{project_id}/artifact.txt", headers=alice_headers)
    bob_file = client.get(f"/files/{project_id}/artifact.txt", headers=bob_headers)
    assert alice_file.status_code == 200
    assert alice_file.text == "private artifact"
    assert bob_file.status_code == 404

    job = main.job_store.create(project_id, JobType.render, owner_id=created.json()["owner_id"])
    assert client.get(f"/jobs/{job.id}", headers=alice_headers).status_code == 200
    assert client.get(f"/jobs/{job.id}", headers=bob_headers).status_code == 404


def test_registration_creates_personal_organization(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ENABLE_USER_AUTH", "true")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    token = client.post(
        "/auth/register",
        json={"email": "workspace@example.com", "password": "strong-password"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    organizations = client.get("/organizations", headers=headers)
    org_id = organizations.json()[0]["id"]
    created = client.post("/projects", json={"topic": "Workspace default project"}, headers=headers)
    members = client.get(f"/organizations/{org_id}/members", headers=headers)

    assert organizations.status_code == 200
    assert organizations.json()[0]["role"] == "owner"
    assert created.status_code == 200
    assert created.json()["organization_id"] == org_id
    assert members.status_code == 200
    assert members.json()[0]["role"] == "owner"


def test_organization_rbac_controls_project_access(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ENABLE_USER_AUTH", "true")
    monkeypatch.setenv("RUN_JOBS_INLINE", "true")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    alice_token = client.post(
        "/auth/register",
        json={"email": "org-alice@example.com", "password": "strong-password"},
    ).json()["access_token"]
    bob_token = client.post(
        "/auth/register",
        json={"email": "org-bob@example.com", "password": "strong-password"},
    ).json()["access_token"]
    viewer_token = client.post(
        "/auth/register",
        json={"email": "org-viewer@example.com", "password": "strong-password"},
    ).json()["access_token"]
    alice_headers = {"Authorization": f"Bearer {alice_token}"}
    bob_headers = {"Authorization": f"Bearer {bob_token}"}
    viewer_headers = {"Authorization": f"Bearer {viewer_token}"}

    org_id = client.get("/organizations", headers=alice_headers).json()[0]["id"]
    bob_member = client.post(
        f"/organizations/{org_id}/members",
        json={"email": "org-bob@example.com", "role": "editor"},
        headers=alice_headers,
    )
    viewer_member = client.post(
        f"/organizations/{org_id}/members",
        json={"email": "org-viewer@example.com", "role": "viewer"},
        headers=alice_headers,
    )
    editor_cannot_invite = client.post(
        f"/organizations/{org_id}/members",
        json={"email": "org-viewer@example.com", "role": "viewer"},
        headers=bob_headers,
    )

    created = client.post(
        "/projects",
        json={"topic": "Shared organization video project", "organization_id": org_id},
        headers=alice_headers,
    )
    project_id = created.json()["id"]
    bob_projects = client.get("/projects", headers=bob_headers)
    bob_update = client.patch(
        f"/projects/{project_id}",
        json={"topic": "Shared organization video project updated"},
        headers=bob_headers,
    )
    viewer_read = client.get(f"/projects/{project_id}", headers=viewer_headers)
    viewer_update = client.patch(
        f"/projects/{project_id}",
        json={"topic": "Viewer should not update"},
        headers=viewer_headers,
    )
    viewer_job = client.post(f"/projects/{project_id}/jobs/generate_script", headers=viewer_headers)
    bob_delete = client.delete(f"/projects/{project_id}", headers=bob_headers)
    alice_delete = client.delete(f"/projects/{project_id}", headers=alice_headers)

    assert bob_member.status_code == 200
    assert viewer_member.status_code == 200
    assert editor_cannot_invite.status_code == 403
    assert created.status_code == 200
    assert created.json()["organization_id"] == org_id
    assert [project["id"] for project in bob_projects.json()] == [project_id]
    assert bob_update.status_code == 200
    assert viewer_read.status_code == 200
    assert viewer_update.status_code == 403
    assert viewer_job.status_code == 403
    assert bob_delete.status_code == 403
    assert alice_delete.status_code == 204


def test_avatar_job_requires_legal_consent(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ENABLE_USER_AUTH", "true")
    monkeypatch.setenv("RUN_JOBS_INLINE", "true")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    token = client.post(
        "/auth/register",
        json={"email": "avatar-consent@example.com", "password": "strong-password"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        "/projects",
        json={"topic": "Avatar consent project", "avatar_enabled": True},
        headers=headers,
    )
    project_id = created.json()["id"]

    blocked = client.post(f"/projects/{project_id}/jobs/prepare_avatar", headers=headers)
    consent = client.post(
        "/consents",
        json={"consent_type": "avatar", "project_id": project_id, "granted": True},
        headers=headers,
    )
    allowed = client.post(f"/projects/{project_id}/jobs/prepare_avatar", headers=headers)
    records = client.get(f"/consents?project_id={project_id}", headers=headers)

    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "consent_required"
    assert blocked.json()["detail"]["missing"][0]["consent_type"] == "avatar"
    assert consent.status_code == 200
    assert consent.json()["consent_type"] == "avatar"
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "completed"
    assert records.status_code == 200
    assert records.json()[0]["granted"] is True


def test_ai_voice_generation_requires_legal_consent(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ENABLE_USER_AUTH", "true")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    token = client.post(
        "/auth/register",
        json={"email": "voice-consent@example.com", "password": "strong-password"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        "/projects",
        json={"topic": "Voice consent project", "voice_provider": "openai", "voice_id": "alloy"},
        headers=headers,
    )
    project_id = created.json()["id"]
    scripted = client.post(f"/projects/{project_id}/generate-script", headers=headers)

    blocked = client.post(f"/projects/{project_id}/generate-voice", headers=headers)
    consent = client.post(
        "/consents",
        json={"consent_type": "voice", "project_id": project_id, "voice_id": "alloy", "granted": True},
        headers=headers,
    )
    allowed = client.post(f"/projects/{project_id}/generate-voice", headers=headers)

    assert scripted.status_code == 200
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["missing"][0]["consent_type"] == "voice"
    assert consent.status_code == 200
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "voice_ready"
    assert allowed.json()["result"]["voice_manifest_url"]


def test_audit_log_records_user_project_and_job_actions(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ENABLE_USER_AUTH", "true")
    monkeypatch.setenv("RUN_JOBS_INLINE", "true")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    token = client.post(
        "/auth/register",
        json={"email": "audit@example.com", "password": "strong-password"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post("/projects", json={"topic": "Audit tracked video project"}, headers=headers)
    project_id = created.json()["id"]
    job = client.post(f"/projects/{project_id}/jobs/generate_script", headers=headers)

    events = client.get("/audit/events?limit=10&offset=0", headers=headers)
    actions = {event["action"] for event in events.json()}

    assert job.status_code == 200
    assert events.status_code == 200
    assert events.headers["x-total-count"] == "3"
    assert {"auth.register", "project.create", "job.start"}.issubset(actions)
    assert all(event["actor_id"] == created.json()["owner_id"] for event in events.json())
    assert all(event["request_id"] for event in events.json())


def test_audit_log_is_isolated_between_users(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ENABLE_USER_AUTH", "true")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    alice = client.post(
        "/auth/register",
        json={"email": "audit-alice@example.com", "password": "strong-password"},
    ).json()["access_token"]
    bob = client.post(
        "/auth/register",
        json={"email": "audit-bob@example.com", "password": "strong-password"},
    ).json()["access_token"]
    alice_headers = {"Authorization": f"Bearer {alice}"}
    bob_headers = {"Authorization": f"Bearer {bob}"}

    created = client.post("/projects", json={"topic": "Alice audit project"}, headers=alice_headers)
    project_id = created.json()["id"]

    alice_project_events = client.get(
        f"/audit/events?resource_type=project&resource_id={project_id}",
        headers=alice_headers,
    )
    bob_project_events = client.get(
        f"/audit/events?resource_type=project&resource_id={project_id}",
        headers=bob_headers,
    )

    assert alice_project_events.status_code == 200
    assert [event["action"] for event in alice_project_events.json()] == ["project.create"]
    assert bob_project_events.status_code == 200
    assert bob_project_events.json() == []


def test_usage_endpoint_tracks_project_and_job_events(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ENABLE_USER_AUTH", "true")
    monkeypatch.setenv("RUN_JOBS_INLINE", "true")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    token = client.post(
        "/auth/register",
        json={"email": "usage@example.com", "password": "strong-password"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        "/projects",
        json={"topic": "Usage tracked video project", "script_provider": "openai"},
        headers=headers,
    )
    project_id = created.json()["id"]
    job = client.post(f"/projects/{project_id}/jobs/generate_script", headers=headers)

    usage = client.get("/usage/me", headers=headers)

    assert job.status_code == 200
    assert usage.status_code == 200
    payload = usage.json()
    assert payload["limits"]["current_projects"] == 1
    assert payload["usage"]["events_by_action"]["project.create"] == 1
    assert payload["usage"]["events_by_action"]["job.start"] == 1
    assert payload["usage"]["estimated_cost_cents"] >= 1


def test_project_quota_blocks_new_projects(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ENABLE_USER_AUTH", "true")
    monkeypatch.setenv("USAGE_MAX_PROJECTS_PER_USER", "1")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    token = client.post(
        "/auth/register",
        json={"email": "quota@example.com", "password": "strong-password"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    first = client.post("/projects", json={"topic": "First quota project"}, headers=headers)
    second = client.post("/projects", json={"topic": "Second quota project"}, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 402
    assert second.json()["detail"]["code"] == "project_quota_exceeded"


def test_api_key_and_user_auth_are_both_required_when_enabled(tmp_path, monkeypatch):
    api_key = "prod-api-key-with-more-than-thirty-two-characters"
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_KEY", api_key)
    monkeypatch.setenv("ENABLE_USER_AUTH", "true")
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    auth = client.post(
        "/auth/register",
        json={"email": "both@example.com", "password": "strong-password"},
    )
    assert auth.status_code == 200
    token = auth.json()["access_token"]

    assert client.get("/projects", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.get("/projects", headers={"x-api-key": api_key}).status_code == 401
    ok = client.get("/projects", headers={"x-api-key": api_key, "Authorization": f"Bearer {token}"})
    assert ok.status_code == 200


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


def test_observability_metrics_collects_requests(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    assert client.get("/health").status_code == 200
    response = client.get("/observability/metrics")

    assert response.status_code == 200
    metrics = response.json()["metrics"]
    assert metrics["total_requests"] >= 1
    assert metrics["by_status"]["200"] >= 1
    assert metrics["by_path"]["GET /health"] >= 1


def test_api_project_manifest_reports_readiness_and_missing_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    created = client.post("/projects", json={"topic": "РўРµСЃС‚РѕРІС‹Р№ API manifest РїСЂРѕРµРєС‚"})
    assert created.status_code == 200
    project_id = created.json()["id"]
    project = main.store.get(project_id)
    project.result.final_video_path = str(main.store.project_dir(project_id) / "missing.mp4")
    main.store.save(project)

    response = client.get(f"/projects/{project_id}/manifest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == project_id
    assert payload["readiness"]["script"] is False
    assert payload["readiness"]["publish_ready"] is False
    assert payload["counts"]["missing_artifacts"] == 1
    assert payload["missing_artifacts"] == ["final_video"]
    assert payload["artifacts"][0]["key"] == "final_video"
    assert payload["artifacts"][0]["exists"] is False


def test_maintenance_backup_and_restore_preview(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    created = client.post("/projects", json={"topic": "Backup smoke test project"})
    assert created.status_code == 200
    project_id = created.json()["id"]

    backup = client.post("/maintenance/backups")
    assert backup.status_code == 200
    backup_id = backup.json()["id"]
    assert backup.json()["files_added"] >= 1

    backups = client.get("/maintenance/backups")
    download = client.get(f"/maintenance/backups/{backup_id}")
    restored = client.post(f"/maintenance/backups/{backup_id}/restore-preview")

    assert backups.status_code == 200
    assert backups.json()[0]["id"] == backup_id
    assert download.status_code == 200
    assert restored.status_code == 200
    restore_path = Path(restored.json()["restore_path"])
    assert (restore_path / project_id / "project.json").is_file()


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


def test_api_rejects_large_request_body(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", "32")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    response = client.post("/projects", json={"topic": "x" * 240})

    assert response.status_code == 413
    assert response.headers["x-request-id"]


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
