from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from app.config import ConfigurationError, Settings, get_settings
from app.models import JobStatus, JobType, ProjectCreate, ProjectStatus, SceneCreate, ScenePatch, SceneReorder, ScriptProviderName, SourceKind, UserCreate, UserSession, VideoStyle, VisualMode, VoiceProviderName
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
from app.utils.security import InvalidIdentifierError, UnsafePathError


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        data_dir=tmp_path,
        public_base_url="http://test",
        log_level="INFO",
        json_logs=False,
        ffmpeg_bin="ffmpeg",
        render_width=1920,
        render_height=1080,
        render_fps=15,
        project_storage_backend="local",
        database_url=None,
        database_connect_timeout_seconds=10,
        database_auto_migrate=True,
        audit_storage_backend="local",
        support_storage_backend="local",
        idempotency_storage_backend="local",
        usage_storage_backend="local",
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
        enable_model_images=False,
        openai_image_model="gpt-image-1",
        openai_image_size="1536x1024",
        heygen_api_key=None,
        heygen_api_base_url="https://api.heygen.com",
        heygen_avatar_id=None,
        heygen_voice_id=None,
        heygen_resolution="1080p",
        heygen_output_format="mp4",
        heygen_remove_background=True,
        heygen_enable_motion_prompt=False,
        heygen_poll_seconds=0,
        heygen_webhook_secret=None,
        heygen_webhook_tolerance_seconds=300,
        avatar_auto_sync_enabled=False,
        avatar_auto_sync_interval_seconds=60,
        avatar_auto_render_after_sync=True,
        burn_subtitles_by_default=False,
        run_jobs_inline=True,
        execute_jobs_in_api=True,
        job_workers=1,
        job_storage_backend="local",
        api_key=None,
        admin_api_key=None,
        enable_user_auth=False,
        access_token_ttl_minutes=1440,
        oidc_enabled=False,
        oidc_issuer_url=None,
        oidc_audience=None,
        oidc_jwks_url=None,
        oidc_algorithms=["RS256"],
        oidc_email_claim="email",
        oidc_name_claim="name",
        rate_limit_requests_per_minute=0,
        cors_origins=["http://localhost:19006"],
        allow_unsafe_http_sources=False,
        allow_private_source_urls=False,
        search_provider="disabled",
        brave_search_api_key=None,
        brave_search_endpoint="https://api.search.brave.com/res/v1/web/search",
        search_result_count=3,
        artifact_storage_backend="local",
        artifact_url_ttl_seconds=3600,
        s3_bucket=None,
        s3_region=None,
        s3_endpoint_url=None,
        s3_access_key_id=None,
        s3_secret_access_key=None,
        s3_prefix="ai-video-studio",
        s3_public_base_url=None,
        cleanup_retention_days=14,
        render_timeout_seconds=1800,
        max_request_body_bytes=2_000_000,
        usage_max_projects_per_user=25,
        usage_max_active_jobs_per_user=2,
        usage_llm_job_cost_cents=1,
        usage_tts_cost_cents_per_minute=1,
        usage_render_cost_cents_per_minute=2,
        stripe_api_key=None,
        stripe_api_version="2026-02-25.clover",
        stripe_webhook_secret=None,
        stripe_pro_price_id=None,
        stripe_success_url="http://localhost:19006/billing/success",
        stripe_cancel_url="http://localhost:19006/billing/cancel",
        stripe_portal_return_url="http://localhost:19006/billing",
        billing_pro_max_projects=250,
        billing_pro_max_active_jobs=10,
    )


def make_pipeline(settings: Settings, store: ProjectStore) -> VideoPipeline:
    return VideoPipeline(
        store=store,
        compliance=ComplianceService(),
        script=ScriptService(settings),
        sources=SourceService(settings),
        visuals=VisualService(settings),
        voice=VoiceService(settings),
        avatar=AvatarService(settings),
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


def test_visual_service_writes_render_template_manifest(tmp_path):
    settings = make_settings(tmp_path)
    store = ProjectStore(settings)
    project = store.create_project(
        ProjectCreate(
            topic="Production render templates for AI video",
            duration_minutes=1,
            visual_mode=VisualMode.official_sites_plus_ai,
            source_urls=["https://example.com/"],
        )
    )
    pipeline = make_pipeline(settings, store)
    result = pipeline.generate_script(project.id)
    result = pipeline.collect_sources(result.id)
    result = pipeline.generate_slides(result.id)

    manifest_path = store.project_dir(result.id) / "slides" / "render_templates.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    template_ids = {item["template_id"] for item in manifest}

    assert manifest_path.exists()
    assert len(manifest) == len(result.scenes)
    assert "source_review_v1" in template_ids
    assert len(template_ids) >= 2
    assert all(item["layout"] for item in manifest)


def test_ai_news_avatar_style_generates_avatar_screen_and_broll_storyboard(tmp_path):
    settings = make_settings(tmp_path)
    store = ProjectStore(settings)
    project = store.create_project(
        ProjectCreate(
            topic="AI-аватар для YouTube-роликов",
            duration_minutes=2,
            style=VideoStyle.ai_news_avatar,
            visual_mode=VisualMode.official_sites_plus_ai,
            source_urls=["https://www.heygen.com/", "https://runwayml.com/"],
            avatar_enabled=True,
            avatar_position="bottom_left",
            burn_subtitles=True,
        )
    )
    pipeline = make_pipeline(settings, store)
    result = pipeline.generate_script(project.id)
    visual_types = {scene.visual_type for scene in result.scenes}

    assert result.scenes[0].visual_type == "big_caption"
    assert result.scenes[-1].visual_type == "cta"
    assert {"avatar_fullscreen", "avatar_pip", "screen_demo", "ai_broll", "big_caption", "cta"} <= visual_types
    assert any(scene.avatar_visible and scene.visual_type == "avatar_pip" for scene in result.scenes)

    result = pipeline.collect_sources(result.id)
    assert any(scene.visual_type == "screen_demo" and scene.source_id for scene in result.scenes)
    assert result.result.visual_plan_path
    visual_plan_path = Path(result.result.visual_plan_path)
    visual_plan = json.loads(visual_plan_path.read_text(encoding="utf-8"))
    assert visual_plan_path.exists()
    assert any(item["visual_type"] == "screen_demo" and item["source_query"] and item["source_id"] for item in visual_plan)
    assert all(scene.source_query for scene in result.scenes if scene.visual_type == "screen_demo")

    result = pipeline.generate_slides(result.id)
    manifest_path = store.project_dir(result.id) / "slides" / "render_templates.json"
    visual_assets_path = Path(result.result.visual_assets_manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    visual_assets = json.loads(visual_assets_path.read_text(encoding="utf-8"))
    template_ids = {item["template_id"] for item in manifest}
    avatar_modes = {item["avatar_mode"] for item in manifest}
    asset_roles = {item["asset_role"] for item in manifest}
    visual_strategies = {item["strategy"] for item in visual_assets}
    screen_templates = [item for item in manifest if item["visual_type"] == "screen_demo"]

    assert {
        "avatar_fullscreen_v1",
        "avatar_pip_v1",
        "screen_demo_v1",
        "ai_broll_v1",
        "big_caption_v1",
        "cta_v1",
    } <= template_ids
    assert {"fullscreen", "picture_in_picture"} <= avatar_modes
    assert {"avatar_host", "screen_recording_or_source_insert", "generated_broll", "call_to_action"} <= asset_roles
    assert "platform_screenshot_or_fallback_card" in visual_strategies
    assert screen_templates
    assert "source_screenshot" in screen_templates[0]["composition_layers"]
    assert screen_templates[0]["replacement_slots"]["source_query"]
    assert visual_assets_path.exists()
    assert all(Path(scene.visual_path).exists() for scene in result.scenes)


def test_prepare_avatar_writes_manifest_without_heygen(tmp_path):
    settings = make_settings(tmp_path)
    store = ProjectStore(settings)
    project = store.create_project(
        ProjectCreate(
            topic="AI-аватар для новостного YouTube-ролика",
            duration_minutes=1,
            style=VideoStyle.ai_news_avatar,
            avatar_enabled=True,
        )
    )
    pipeline = make_pipeline(settings, store)
    result = pipeline.generate_script(project.id)
    result = pipeline.prepare_avatar(result.id)
    manifest_path = Path(result.result.avatar_manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest_path.exists()
    assert manifest["provider"] == "heygen"
    assert manifest["status"] == "provider_not_configured"
    assert manifest["scene_count"] > 0
    assert all(item["status"] == "placeholder" for item in manifest["scenes"])
    assert any("HeyGen не подключён" in warning for warning in result.result.warnings)


def test_prepare_avatar_submits_heygen_jobs_when_configured(tmp_path, monkeypatch):
    from app.services import avatar_service as avatar_service_module

    settings = Settings(
        **{
            **make_settings(tmp_path).__dict__,
            "heygen_api_key": "heygen-test-key",
            "heygen_avatar_id": "avatar_test",
            "heygen_voice_id": "voice_test",
        }
    )
    store = ProjectStore(settings)
    project = store.create_project(
        ProjectCreate(
            topic="AI-ведущий показывает платформы для ролика",
            duration_minutes=1,
            style=VideoStyle.ai_news_avatar,
            avatar_enabled=True,
        )
    )
    pipeline = make_pipeline(settings, store)

    class FakeHeyGenProvider:
        def __init__(self, settings):
            self.settings = settings

        def create_avatar_video(self, project, scene):
            return {"video_id": f"vid_{scene.order:03d}", "status": "queued", "output_format": "mp4"}

        def get_video(self, video_id):
            return {"id": video_id, "status": "queued"}

    monkeypatch.setattr(avatar_service_module, "HeyGenAvatarProvider", FakeHeyGenProvider)

    result = pipeline.generate_script(project.id)
    result = pipeline.prepare_avatar(result.id)
    avatar_scenes = [scene for scene in result.scenes if scene.avatar_visible and scene.visual_type in {"avatar_fullscreen", "avatar_pip", "screen_demo", "cta"}]
    manifest = json.loads(Path(result.result.avatar_manifest_path).read_text(encoding="utf-8"))

    assert avatar_scenes
    assert all(scene.avatar_video_id for scene in avatar_scenes)
    assert {item["heygen_status"] for item in manifest["scenes"]} == {"queued"}
    assert manifest["configured"] is True


def test_sync_avatar_downloads_completed_heygen_videos(tmp_path, monkeypatch):
    from app.services import avatar_service as avatar_service_module

    settings = Settings(
        **{
            **make_settings(tmp_path).__dict__,
            "heygen_api_key": "heygen-test-key",
            "heygen_avatar_id": "avatar_test",
            "heygen_voice_id": "voice_test",
        }
    )
    store = ProjectStore(settings)
    project = store.create_project(
        ProjectCreate(
            topic="AI-ведущий ждёт готовые HeyGen-ассеты",
            duration_minutes=1,
            style=VideoStyle.ai_news_avatar,
            avatar_enabled=True,
        )
    )
    pipeline = make_pipeline(settings, store)

    class FakeHeyGenProvider:
        def __init__(self, settings):
            self.settings = settings

        def create_avatar_video(self, project, scene):
            raise AssertionError("sync must not submit new HeyGen jobs")

        def get_video(self, video_id):
            return {"id": video_id, "status": "completed", "video_url": f"https://video.local/{video_id}.mp4"}

        def download_video(self, video_url, output_path):
            output_path.write_bytes(f"fake mp4 from {video_url}".encode("utf-8"))
            return output_path

    monkeypatch.setattr(avatar_service_module, "HeyGenAvatarProvider", FakeHeyGenProvider)

    project = pipeline.generate_script(project.id)
    for scene in project.scenes:
        if scene.avatar_visible and scene.visual_type in {"avatar_fullscreen", "avatar_pip", "screen_demo", "cta"}:
            scene.avatar_video_id = f"vid_{scene.order:03d}"
            scene.avatar_video_status = "queued"
    store.save(project)

    result = pipeline.sync_avatar(project.id)
    manifest = json.loads(Path(result.result.avatar_manifest_path).read_text(encoding="utf-8"))
    avatar_scenes = [scene for scene in result.scenes if scene.avatar_visible and scene.visual_type in {"avatar_fullscreen", "avatar_pip", "screen_demo", "cta"}]

    assert manifest["mode"] == "sync"
    assert manifest["status"] == "ready"
    assert avatar_scenes
    assert all(scene.avatar_video_status == "completed" for scene in avatar_scenes)
    assert all(scene.avatar_video_path and Path(scene.avatar_video_path).exists() for scene in avatar_scenes)


def test_inline_job_runner_sync_avatar_job(tmp_path, monkeypatch):
    from app.services import avatar_service as avatar_service_module

    settings = Settings(
        **{
            **make_settings(tmp_path).__dict__,
            "heygen_api_key": "heygen-test-key",
            "heygen_avatar_id": "avatar_test",
            "heygen_voice_id": "voice_test",
        }
    )
    store = ProjectStore(settings)
    pipeline = make_pipeline(settings, store)
    job_store = JobStore(settings)
    runner = JobRunner(settings, pipeline, job_store)
    project = store.create_project(
        ProjectCreate(
            topic="Фоновая синхронизация HeyGen avatar MP4",
            duration_minutes=1,
            style=VideoStyle.ai_news_avatar,
            avatar_enabled=True,
        )
    )

    class FakeHeyGenProvider:
        def __init__(self, settings):
            self.settings = settings

        def create_avatar_video(self, project, scene):
            raise AssertionError("sync_avatar job must not create new HeyGen jobs")

        def get_video(self, video_id):
            return {"id": video_id, "status": "completed", "video_url": f"https://video.local/{video_id}.mp4"}

        def download_video(self, video_url, output_path):
            output_path.write_bytes(b"fake mp4")
            return output_path

    monkeypatch.setattr(avatar_service_module, "HeyGenAvatarProvider", FakeHeyGenProvider)

    project = pipeline.generate_script(project.id)
    for scene in project.scenes:
        if scene.avatar_visible and scene.visual_type in {"avatar_fullscreen", "avatar_pip", "screen_demo", "cta"}:
            scene.avatar_video_id = f"vid_{scene.order:03d}"
            scene.avatar_video_status = "queued"
    store.save(project)

    job = runner.start(project.id, JobType.sync_avatar)
    saved_job = job_store.get(job.id)
    result = store.get(project.id)
    avatar_scenes = [scene for scene in result.scenes if scene.avatar_visible and scene.visual_type in {"avatar_fullscreen", "avatar_pip", "screen_demo", "cta"}]

    assert saved_job.status == JobStatus.completed
    assert saved_job.progress == 100
    assert saved_job.current_step == "completed"
    assert result.current_step == "avatar_synced"
    assert avatar_scenes
    assert all(scene.avatar_video_path and Path(scene.avatar_video_path).exists() for scene in avatar_scenes)


def test_job_runner_queues_avatar_sync_candidates_with_backoff(tmp_path):
    settings = Settings(
        **{
            **make_settings(tmp_path).__dict__,
            "heygen_api_key": "heygen-test-key",
            "heygen_avatar_id": "avatar_test",
            "run_jobs_inline": False,
            "execute_jobs_in_api": False,
            "avatar_auto_sync_enabled": True,
            "avatar_auto_sync_interval_seconds": 60,
        }
    )
    store = ProjectStore(settings)
    pipeline = make_pipeline(settings, store)
    job_store = JobStore(settings)
    runner = JobRunner(settings, pipeline, job_store)
    project = store.create_project(
        ProjectCreate(
            topic="Worker сам найдёт pending avatar video",
            duration_minutes=1,
            style=VideoStyle.ai_news_avatar,
            avatar_enabled=True,
        )
    )
    project = pipeline.generate_script(project.id)
    target = next(scene for scene in project.scenes if scene.avatar_visible and scene.visual_type in {"avatar_fullscreen", "avatar_pip", "screen_demo", "cta"})
    target.avatar_video_id = "vid_pending"
    target.avatar_video_status = "processing"
    store.save(project)

    queued = runner.queue_avatar_sync_candidates(limit=5)
    queued_again = runner.queue_avatar_sync_candidates(limit=5)

    assert len(queued) == 1
    assert queued[0].type == JobType.sync_avatar
    assert queued[0].status == JobStatus.queued
    assert queued_again == []
    assert job_store.active_for_project(project.id).id == queued[0].id


def test_sync_avatar_job_auto_renders_when_avatar_assets_ready(tmp_path, monkeypatch):
    from app.services import avatar_service as avatar_service_module

    settings = Settings(
        **{
            **make_settings(tmp_path).__dict__,
            "heygen_api_key": "heygen-test-key",
            "heygen_avatar_id": "avatar_test",
            "heygen_voice_id": "voice_test",
            "avatar_auto_render_after_sync": True,
        }
    )
    store = ProjectStore(settings)
    pipeline = make_pipeline(settings, store)
    job_store = JobStore(settings)
    runner = JobRunner(settings, pipeline, job_store)
    project = store.create_project(
        ProjectCreate(
            topic="Auto render после готовности HeyGen avatar MP4",
            duration_minutes=1,
            style=VideoStyle.ai_news_avatar,
            avatar_enabled=True,
        )
    )

    class FakeHeyGenProvider:
        def __init__(self, settings):
            self.settings = settings

        def create_avatar_video(self, project, scene):
            raise AssertionError("sync_avatar auto-render test must not create HeyGen jobs")

        def get_video(self, video_id):
            return {"id": video_id, "status": "completed", "video_url": f"https://video.local/{video_id}.mp4"}

        def download_video(self, video_url, output_path):
            output_path.write_bytes(b"fake avatar mp4 placeholder")
            return output_path

    monkeypatch.setattr(avatar_service_module, "HeyGenAvatarProvider", FakeHeyGenProvider)

    project = pipeline.generate_script(project.id)
    project = pipeline.generate_slides(project.id)
    project = pipeline.generate_voice(project.id)
    for scene in project.scenes:
        if scene.avatar_visible and scene.visual_type in {"avatar_fullscreen", "avatar_pip", "screen_demo", "cta"}:
            scene.avatar_video_id = f"vid_{scene.order:03d}"
            scene.avatar_video_status = "processing"
    store.save(project)

    render_calls: list[str] = []

    def fake_render(project_id: str):
        render_calls.append(project_id)
        fresh = store.get(project_id)
        final_path = store.project_dir(project_id) / "video" / "final.mp4"
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_bytes(b"fake final mp4")
        fresh.result.final_video_path = str(final_path)
        fresh.status = ProjectStatus.completed
        fresh.error = None
        fresh.touch("completed")
        store.save(fresh)
        return fresh

    pipeline.render = fake_render

    job = runner.start(project.id, JobType.sync_avatar)
    saved_job = job_store.get(job.id)
    result = store.get(project.id)

    assert saved_job.status == JobStatus.completed
    assert render_calls == [project.id]
    assert result.status == ProjectStatus.completed
    assert Path(result.result.final_video_path).exists()
    assert any(event["message"] == "starting_auto_render" for event in saved_job.events)


def test_heygen_webhook_updates_scene_and_is_idempotent(tmp_path, monkeypatch):
    from app.services import avatar_service as avatar_service_module

    secret = "webhook-secret"
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("HEYGEN_API_KEY", "heygen-test-key")
    monkeypatch.setenv("HEYGEN_AVATAR_ID", "avatar_test")
    monkeypatch.setenv("HEYGEN_WEBHOOK_SECRET", secret)
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")

    class FakeHeyGenProvider:
        def __init__(self, settings):
            self.settings = settings

        def download_video(self, video_url, output_path):
            output_path.write_bytes(f"downloaded {video_url}".encode("utf-8"))
            return output_path

    monkeypatch.setattr(avatar_service_module, "HeyGenAvatarProvider", FakeHeyGenProvider)
    client = TestClient(main.app)
    project = main.store.create_project(
        ProjectCreate(
            topic="HeyGen webhook обновляет avatar MP4",
            duration_minutes=1,
            style=VideoStyle.ai_news_avatar,
            avatar_enabled=True,
        )
    )
    project = main.pipeline.generate_script(project.id)
    target = next(scene for scene in project.scenes if scene.avatar_visible and scene.visual_type in {"avatar_fullscreen", "avatar_pip", "screen_demo", "cta"})
    target.avatar_video_id = "video_123"
    target.avatar_video_status = "processing"
    main.store.save(project)

    payload = {
        "event_type": "video.completed",
        "event_data": {"video_id": "video_123", "url": "https://video.local/video_123.mp4"},
    }
    raw_body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    headers = {
        "content-type": "application/json",
        "Heygen-Signature": hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest(),
        "Heygen-Timestamp": str(int(time.time())),
        "Heygen-Event-Id": "evt_test_123456",
    }

    response = client.post("/webhooks/heygen", content=raw_body, headers=headers)
    replay = client.post("/webhooks/heygen", content=raw_body, headers=headers)

    assert response.status_code == 200
    assert response.json()["processed"] is True
    assert replay.status_code == 200
    assert replay.json()["duplicate"] is True
    assert replay.headers["x-idempotent-replay"] == "true"
    updated = main.store.get(project.id)
    updated_scene = next(scene for scene in updated.scenes if scene.id == target.id)
    assert updated.current_step == "avatar_webhook_synced"
    assert updated_scene.avatar_video_status == "completed"
    assert updated_scene.avatar_video_url == "https://video.local/video_123.mp4"
    assert updated_scene.avatar_video_path and Path(updated_scene.avatar_video_path).exists()
    manifest = json.loads(Path(updated.result.avatar_manifest_path).read_text(encoding="utf-8"))
    assert manifest["mode"] == "webhook"


def test_heygen_webhook_rejects_invalid_signature(tmp_path, monkeypatch):
    secret = "webhook-secret"
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("HEYGEN_API_KEY", "heygen-test-key")
    monkeypatch.setenv("HEYGEN_AVATAR_ID", "avatar_test")
    monkeypatch.setenv("HEYGEN_WEBHOOK_SECRET", secret)
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)
    raw_body = b'{"event_type":"avatar_video.success","event_data":{"video_id":"video_123"}}'

    response = client.post(
        "/webhooks/heygen",
        content=raw_body,
        headers={
            "content-type": "application/json",
            "Heygen-Signature": "bad",
            "Heygen-Timestamp": str(int(time.time())),
            "Heygen-Event-Id": "evt_test_654321",
        },
    )

    assert response.status_code == 401


def test_heygen_webhook_queues_render_when_project_ready(tmp_path, monkeypatch):
    from app.services import avatar_service as avatar_service_module

    secret = "webhook-secret"
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("HEYGEN_API_KEY", "heygen-test-key")
    monkeypatch.setenv("HEYGEN_AVATAR_ID", "avatar_test")
    monkeypatch.setenv("HEYGEN_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("RUN_JOBS_INLINE", "false")
    monkeypatch.setenv("EXECUTE_JOBS_IN_API", "false")
    monkeypatch.setenv("AVATAR_AUTO_RENDER_AFTER_SYNC", "true")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")

    class FakeHeyGenProvider:
        def __init__(self, settings):
            self.settings = settings

        def download_video(self, video_url, output_path):
            output_path.write_bytes(b"ready avatar")
            return output_path

    monkeypatch.setattr(avatar_service_module, "HeyGenAvatarProvider", FakeHeyGenProvider)
    client = TestClient(main.app)
    project = main.store.create_project(
        ProjectCreate(
            topic="HeyGen webhook ставит render после готовности",
            duration_minutes=1,
            style=VideoStyle.ai_news_avatar,
            avatar_enabled=True,
        )
    )
    project = main.pipeline.generate_script(project.id)
    project = main.pipeline.generate_slides(project.id)
    project = main.pipeline.generate_voice(project.id)
    avatar_dir = main.store.project_dir(project.id) / "assets" / "avatar"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    avatar_scenes = [scene for scene in project.scenes if scene.avatar_visible and scene.visual_type in {"avatar_fullscreen", "avatar_pip", "screen_demo", "cta"}]
    target = avatar_scenes[-1]
    for scene in avatar_scenes:
        scene.avatar_video_id = f"video_{scene.order:03d}"
        scene.avatar_video_status = "completed"
        if scene.id != target.id:
            avatar_path = avatar_dir / f"scene_{scene.order:03d}_heygen.mp4"
            avatar_path.write_bytes(b"ready avatar")
            scene.avatar_video_path = str(avatar_path)
    main.store.save(project)

    payload = {
        "event_type": "video.completed",
        "event_data": {"video_id": target.avatar_video_id, "video_url": "https://video.local/final-avatar.mp4"},
    }
    raw_body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    response = client.post(
        "/webhooks/heygen",
        content=raw_body,
        headers={
            "content-type": "application/json",
            "Heygen-Signature": hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest(),
            "Heygen-Timestamp": str(int(time.time())),
            "Heygen-Event-Id": "evt_render_ready_123",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["render_queued"] is True
    assert payload["render_job_id"]
    render_job = main.job_store.get(payload["render_job_id"])
    assert render_job.type == JobType.render
    assert render_job.status == JobStatus.queued
    assert any(event["event"] == "queued_for_external_worker" for event in render_job.events)
    assert main.store.get(project.id).current_step == "queued_render"


def test_retry_avatar_scene_resets_old_job_and_resubmits_one_scene(tmp_path, monkeypatch):
    from app.services import avatar_service as avatar_service_module

    settings = Settings(
        **{
            **make_settings(tmp_path).__dict__,
            "heygen_api_key": "heygen-test-key",
            "heygen_avatar_id": "avatar_test",
            "heygen_voice_id": "voice_test",
        }
    )
    store = ProjectStore(settings)
    project = store.create_project(
        ProjectCreate(
            topic="Повторная генерация одной avatar-сцены",
            duration_minutes=1,
            style=VideoStyle.ai_news_avatar,
            avatar_enabled=True,
        )
    )
    pipeline = make_pipeline(settings, store)

    class FakeHeyGenProvider:
        def __init__(self, settings):
            self.settings = settings

        def create_avatar_video(self, project, scene):
            return {"video_id": f"retry_{scene.order:03d}", "status": "queued", "output_format": "mp4"}

        def get_video(self, video_id):
            raise AssertionError("retry starts from a clean scene and must submit a new job")

    monkeypatch.setattr(avatar_service_module, "HeyGenAvatarProvider", FakeHeyGenProvider)

    project = pipeline.generate_script(project.id)
    target = next(scene for scene in project.scenes if scene.avatar_visible and scene.visual_type in {"avatar_fullscreen", "avatar_pip", "screen_demo", "cta"})
    target.avatar_video_id = "old_video"
    target.avatar_video_status = "failed"
    target.avatar_video_url = "https://video.local/old.mp4"
    target.avatar_video_path = str(store.project_dir(project.id) / "assets" / "avatar" / "old.mp4")
    store.save(project)

    result = pipeline.retry_avatar_scene(project.id, target.id)
    updated_target = next(scene for scene in result.scenes if scene.id == target.id)
    manifest = json.loads(Path(result.result.avatar_manifest_path).read_text(encoding="utf-8"))

    assert manifest["mode"] == "retry"
    assert manifest["scene_count"] == 1
    assert manifest["scenes"][0]["scene_id"] == target.id
    assert updated_target.avatar_video_id == f"retry_{updated_target.order:03d}"
    assert updated_target.avatar_video_status == "queued"
    assert updated_target.avatar_video_url is None
    assert updated_target.avatar_video_path is None


def test_source_service_uses_search_provider_results(tmp_path):
    from app.services.search_provider import SearchResult

    settings = make_settings(tmp_path)
    settings = Settings(**{**settings.__dict__, "search_result_count": 2})
    store = ProjectStore(settings)
    project = store.create_project(
        ProjectCreate(
            topic="AI video research provider",
            duration_minutes=1,
            visual_mode=VisualMode.official_sites_plus_ai,
        )
    )
    service = SourceService(settings)

    class FakeSearchProvider:
        def search(self, query: str, *, count: int, language: str = "en") -> list[SearchResult]:
            assert query == "AI video research provider"
            assert count == 2
            return [
                SearchResult(
                    title="Official Research Result",
                    url="https://example.com/research",
                    description="Search result description",
                )
            ]

    service.search_provider = FakeSearchProvider()
    service.search_provider_error = None

    result = service.collect_sources(project, store.project_dir(project.id))

    assert any(source.kind == SourceKind.search_result for source in result.sources)
    assert any(source.url == "https://example.com/research" for source in result.sources)


def test_brave_search_provider_filters_unsafe_results(tmp_path):
    from app.services.search_provider import BraveSearchProvider

    settings = make_settings(tmp_path)
    settings = Settings(
        **{
            **settings.__dict__,
            "search_provider": "brave",
            "brave_search_api_key": "test-token",
        }
    )
    provider = BraveSearchProvider(settings)

    results = provider._parse_results(
        {
            "web": {
                "results": [
                    {"title": "Safe", "url": "https://example.com/safe", "description": "ok"},
                    {"title": "Local", "url": "http://127.0.0.1/private", "description": "blocked"},
                ]
            }
        }
    )

    assert len(results) == 1
    assert results[0].url == "https://example.com/safe"


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
    assert project_stats["storage_backend"] == "local"
    assert project_stats["projects_by_status"]["draft"] == 1
    assert project_stats["storage_files"] >= 2
    assert job_stats["storage_backend"] == "local"
    assert job_stats["job_count"] == 1
    assert job_stats["terminal_jobs"] == 1
    assert job_stats["jobs_by_status"]["cancelled"] == 1
    assert job_stats["jobs_by_type"]["generate_script"] == 1


def test_project_store_reports_local_backend(tmp_path):
    settings = make_settings(tmp_path)
    store = ProjectStore(settings)

    assert store.metadata()["backend"] == "local"
    assert store.health() is True


def test_job_store_reports_local_backend(tmp_path):
    settings = make_settings(tmp_path)
    job_store = JobStore(settings)

    assert job_store.metadata()["backend"] == "local"
    assert job_store.health() is True


def test_audit_log_reports_local_backend(tmp_path):
    from app.services.audit_log_service import AuditLogService

    settings = make_settings(tmp_path)
    audit_log = AuditLogService(settings)

    assert audit_log.metadata()["backend"] == "local"
    assert audit_log.metadata()["events_dir"].endswith("/_audit")


def test_support_service_reports_local_backend(tmp_path):
    from app.services.support_service import SupportService

    settings = make_settings(tmp_path)
    support = SupportService(settings)

    assert support.metadata()["backend"] == "local"
    assert support.metadata()["ticket_count"] == 0
    assert support.metadata()["tickets_dir"].endswith("/_support/tickets")


def test_idempotency_store_reports_local_backend(tmp_path):
    from app.services.idempotency_service import IdempotencyStore

    settings = make_settings(tmp_path)
    store = IdempotencyStore(settings)

    assert store.metadata()["backend"] == "local"
    assert store.metadata()["record_count"] == 0
    assert store.metadata()["records_dir"].endswith("/_idempotency")


def test_usage_service_reports_local_backend(tmp_path):
    from app.services.usage_service import UsageService

    settings = make_settings(tmp_path)
    usage = UsageService(settings)
    usage.record("job.start", actor_id="user_aaaaaaaaaaaa", units=2, estimated_cost_cents=3)

    assert usage.metadata()["backend"] == "local"
    assert usage.metadata()["event_count"] == 1
    assert usage.metadata()["total_units"] == 2
    assert usage.metadata()["estimated_cost_cents"] == 3
    assert usage.metadata()["events_dir"].endswith("/_usage")


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


def test_render_service_composites_local_avatar_video(tmp_path):
    settings = make_settings(tmp_path)
    renderer = RenderService(settings)
    ffmpeg_bin = renderer.resolve_ffmpeg_bin()
    if not ffmpeg_bin:
        pytest.skip("FFmpeg is not available")

    store = ProjectStore(settings)
    project = store.create_project(
        ProjectCreate(
            topic="AI-ведущий поверх демонстрации экрана",
            duration_minutes=1,
            style=VideoStyle.ai_news_avatar,
            visual_mode=VisualMode.official_sites_plus_ai,
            source_urls=["https://www.heygen.com/"],
            avatar_enabled=True,
            avatar_position="bottom_left",
        )
    )
    pipeline = make_pipeline(settings, store)
    project = pipeline.generate_script(project.id)
    project = pipeline.collect_sources(project.id)
    project = pipeline.generate_slides(project.id)
    project = pipeline.generate_voice(project.id)

    avatar_dir = store.project_dir(project.id) / "assets" / "avatar"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    avatar_path = avatar_dir / "test_avatar.mp4"
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x2563eb:s=320x180:r=15",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(avatar_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    avatar_scene = next(scene for scene in project.scenes if scene.visual_type in {"avatar_pip", "screen_demo", "cta"})
    avatar_scene.avatar_video_id = "test_avatar_video"
    avatar_scene.avatar_video_status = "completed"
    avatar_scene.avatar_video_path = str(avatar_path)
    store.save(project)

    result = pipeline.render(project.id)
    render_manifest = json.loads(Path(result.result.render_manifest_path).read_text(encoding="utf-8"))
    quality_report = json.loads(Path(result.result.quality_report_path).read_text(encoding="utf-8"))

    assert result.status == ProjectStatus.completed
    assert Path(result.result.final_video_path).exists()
    assert render_manifest["render_mode"] == "avatar_video_composite"
    assert render_manifest["production_timeline"]
    assert any(item["uses_source_insert"] for item in render_manifest["production_timeline"])
    assert avatar_scene.id in quality_report["avatar_composited_scene_ids"]
    assert quality_report["checks"]["uses_avatar_video_compositor"] is True
    with ZipFile(result.result.export_package_path) as archive:
        assert "avatar/test_avatar.mp4" in archive.namelist()


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


def test_artifact_store_public_url_entry_and_escape_guard(tmp_path):
    from app.services.artifact_store import ArtifactStore

    settings = make_settings(tmp_path / "data")
    artifact_store = ArtifactStore(settings)
    artifact_path = settings.data_dir / "project_aaaaaaaaaaaa" / "exports" / "result.txt"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text("ok", encoding="utf-8")
    outside_path = tmp_path / "outside.txt"
    outside_path.write_text("secret", encoding="utf-8")

    entry = artifact_store.entry("result_path", str(artifact_path))

    assert artifact_store.public_url(str(artifact_path)) == "http://test/files/project_aaaaaaaaaaaa/exports/result.txt"
    assert entry["exists"] is True
    assert entry["size_bytes"] == 2
    assert entry["storage_backend"] == "local"
    assert artifact_store.public_url(str(outside_path)) is None
    with pytest.raises(UnsafePathError):
        artifact_store.resolve_artifact_path(str(outside_path))


def test_s3_artifact_store_uploads_and_presigns(tmp_path, monkeypatch):
    from app.services import artifact_store as artifact_store_module
    from app.services.artifact_store import ArtifactStore

    class FakeS3Client:
        def __init__(self):
            self.uploads = []

        def upload_file(self, filename, bucket, key, ExtraArgs=None):
            self.uploads.append((filename, bucket, key, ExtraArgs))

        def head_object(self, Bucket, Key):
            return {"ContentLength": 2}

        def generate_presigned_url(self, operation, Params, ExpiresIn):
            return f"https://signed.example/{Params['Bucket']}/{Params['Key']}?ttl={ExpiresIn}"

    class FakeBoto3:
        def __init__(self, client):
            self.client_instance = client

        def client(self, *args, **kwargs):
            return self.client_instance

    fake_client = FakeS3Client()
    monkeypatch.setattr(artifact_store_module, "boto3", FakeBoto3(fake_client))
    settings = Settings(
        **{
            **make_settings(tmp_path / "data").__dict__,
            "artifact_storage_backend": "s3",
            "artifact_url_ttl_seconds": 120,
            "s3_bucket": "studio-artifacts",
            "s3_region": "auto",
            "s3_endpoint_url": "https://r2.example",
            "s3_access_key_id": "key",
            "s3_secret_access_key": "secret",
            "s3_prefix": "tenant-a",
        }
    )
    artifact_path = settings.data_dir / "project_aaaaaaaaaaaa" / "exports" / "result.txt"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text("ok", encoding="utf-8")

    artifact_store = ArtifactStore(settings)
    entry = artifact_store.entry("result_path", str(artifact_path))

    assert entry["exists"] is True
    assert entry["size_bytes"] == 2
    assert entry["storage_backend"] == "s3"
    assert entry["object_key"] == "tenant-a/project_aaaaaaaaaaaa/exports/result.txt"
    assert entry["url"] == "https://signed.example/studio-artifacts/tenant-a/project_aaaaaaaaaaaa/exports/result.txt?ttl=120"
    assert fake_client.uploads[0][1] == "studio-artifacts"
    assert fake_client.uploads[0][2] == "tenant-a/project_aaaaaaaaaaaa/exports/result.txt"
    assert artifact_store.metadata()["signed_urls"] is True


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


def test_get_settings_rejects_unknown_log_level(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_LEVEL", "verbose")

    with pytest.raises(ConfigurationError, match="LOG_LEVEL"):
        get_settings()


def test_get_settings_parses_rate_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "12")
    settings = get_settings()

    assert settings.rate_limit_requests_per_minute == 12


def test_get_settings_rejects_unknown_project_storage_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECT_STORAGE_BACKEND", "sqlite")

    with pytest.raises(ConfigurationError, match="PROJECT_STORAGE_BACKEND"):
        get_settings()


def test_get_settings_requires_database_url_for_postgres_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECT_STORAGE_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        get_settings()


def test_get_settings_rejects_unknown_job_storage_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JOB_STORAGE_BACKEND", "sqlite")

    with pytest.raises(ConfigurationError, match="JOB_STORAGE_BACKEND"):
        get_settings()


def test_get_settings_requires_database_url_for_postgres_job_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JOB_STORAGE_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        get_settings()


def test_get_settings_rejects_unknown_audit_storage_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AUDIT_STORAGE_BACKEND", "sqlite")

    with pytest.raises(ConfigurationError, match="AUDIT_STORAGE_BACKEND"):
        get_settings()


def test_get_settings_requires_database_url_for_postgres_audit_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AUDIT_STORAGE_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        get_settings()


def test_get_settings_rejects_unknown_support_storage_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SUPPORT_STORAGE_BACKEND", "sqlite")

    with pytest.raises(ConfigurationError, match="SUPPORT_STORAGE_BACKEND"):
        get_settings()


def test_get_settings_requires_database_url_for_postgres_support_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SUPPORT_STORAGE_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        get_settings()


def test_get_settings_rejects_unknown_idempotency_storage_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IDEMPOTENCY_STORAGE_BACKEND", "sqlite")

    with pytest.raises(ConfigurationError, match="IDEMPOTENCY_STORAGE_BACKEND"):
        get_settings()


def test_get_settings_requires_database_url_for_postgres_idempotency_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IDEMPOTENCY_STORAGE_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        get_settings()


def test_get_settings_rejects_unknown_usage_storage_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("USAGE_STORAGE_BACKEND", "sqlite")

    with pytest.raises(ConfigurationError, match="USAGE_STORAGE_BACKEND"):
        get_settings()


def test_get_settings_requires_database_url_for_postgres_usage_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("USAGE_STORAGE_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        get_settings()


def test_get_settings_requires_bucket_for_s3_artifact_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ARTIFACT_STORAGE_BACKEND", "s3")
    monkeypatch.delenv("S3_BUCKET", raising=False)

    with pytest.raises(ConfigurationError, match="S3_BUCKET"):
        get_settings()


def test_get_settings_requires_s3_access_key_pair(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ARTIFACT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "key")
    monkeypatch.delenv("S3_SECRET_ACCESS_KEY", raising=False)

    with pytest.raises(ConfigurationError, match="S3_ACCESS_KEY_ID"):
        get_settings()


def test_get_settings_requires_stripe_price_when_api_key_is_set(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STRIPE_API_KEY", "stripe-test-key-placeholder")
    monkeypatch.delenv("STRIPE_PRO_PRICE_ID", raising=False)

    with pytest.raises(ConfigurationError, match="STRIPE_PRO_PRICE_ID"):
        get_settings()


def test_get_settings_requires_stripe_webhook_secret_in_production(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_KEY", "prod-api-key-with-more-than-thirty-two-characters")
    monkeypatch.setenv("STRIPE_API_KEY", "stripe-test-key-placeholder")
    monkeypatch.setenv("STRIPE_PRO_PRICE_ID", "price_test")
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)

    with pytest.raises(ConfigurationError, match="STRIPE_WEBHOOK_SECRET"):
        get_settings()


def test_get_settings_requires_heygen_avatar_id_when_key_is_set(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HEYGEN_API_KEY", "heygen-test-key")
    monkeypatch.delenv("HEYGEN_AVATAR_ID", raising=False)

    with pytest.raises(ConfigurationError, match="HEYGEN_AVATAR_ID"):
        get_settings()


def test_get_settings_requires_openai_key_for_model_images(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ENABLE_MODEL_IMAGES", "true")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
        get_settings()


def test_get_settings_requires_user_auth_for_oidc(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("ENABLE_USER_AUTH", "false")

    with pytest.raises(ConfigurationError, match="ENABLE_USER_AUTH"):
        get_settings()


def test_get_settings_requires_oidc_provider_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("ENABLE_USER_AUTH", "true")
    monkeypatch.setenv("OIDC_ISSUER_URL", "https://issuer.example")
    monkeypatch.setenv("OIDC_AUDIENCE", "youtube-ai-long")
    monkeypatch.delenv("OIDC_JWKS_URL", raising=False)

    with pytest.raises(ConfigurationError, match="OIDC_JWKS_URL"):
        get_settings()


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


def test_oidc_bearer_token_upserts_user_and_personal_org(tmp_path, monkeypatch):
    from app.services.oidc_service import OIDCIdentity

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ENABLE_USER_AUTH", "true")
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("OIDC_ISSUER_URL", "https://issuer.example")
    monkeypatch.setenv("OIDC_AUDIENCE", "youtube-ai-long")
    monkeypatch.setenv("OIDC_JWKS_URL", "https://issuer.example/.well-known/jwks.json")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)
    monkeypatch.setattr(
        main.oidc_service,
        "verify_token",
        lambda token: OIDCIdentity(
            issuer="https://issuer.example",
            subject="external-user-1",
            email="oidc@example.com",
            name="OIDC User",
            claims={"sub": "external-user-1"},
        ),
    )
    headers = {"Authorization": "Bearer external.jwt.token"}

    me = client.get("/auth/me", headers=headers)
    orgs = client.get("/organizations", headers=headers)
    created = client.post("/projects", json={"topic": "OIDC authenticated project"}, headers=headers)

    assert me.status_code == 200
    assert me.json()["email"] == "oidc@example.com"
    assert orgs.status_code == 200
    assert orgs.json()[0]["role"] == "owner"
    assert created.status_code == 200
    assert created.json()["owner_id"] == me.json()["id"]
    assert created.json()["organization_id"] == orgs.json()[0]["id"]


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


def test_billing_me_reports_free_entitlements(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ENABLE_USER_AUTH", "true")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    token = client.post(
        "/auth/register",
        json={"email": "billing-free@example.com", "password": "strong-password"},
    ).json()["access_token"]
    response = client.get("/billing/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["entitlements"]["plan"] == "free"
    assert response.json()["usage_limits"]["max_projects"] == 25


def test_billing_pro_subscription_lifts_project_quota(tmp_path, monkeypatch):
    from app.services.billing_service import BillingAccount

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ENABLE_USER_AUTH", "true")
    monkeypatch.setenv("USAGE_MAX_PROJECTS_PER_USER", "1")
    monkeypatch.setenv("BILLING_PRO_MAX_PROJECTS", "2")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    auth = client.post(
        "/auth/register",
        json={"email": "billing-pro@example.com", "password": "strong-password"},
    ).json()
    token = auth["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    user_id = auth["user"]["id"]
    first = client.post("/projects", json={"topic": "First billed project"}, headers=headers)
    main.billing_service.save_account(
        BillingAccount(
            actor_id=user_id,
            plan="pro",
            status="active",
            stripe_customer_id="cus_test",
            stripe_subscription_id="sub_test",
            stripe_price_id="price_pro",
            current_period_end=None,
            updated_at=datetime.now(timezone.utc),
        )
    )
    second = client.post("/projects", json={"topic": "Second billed project"}, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert client.get("/billing/me", headers=headers).json()["entitlements"]["plan"] == "pro"


def test_stripe_webhook_updates_subscription_state(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ENABLE_USER_AUTH", "true")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    auth = client.post(
        "/auth/register",
        json={"email": "billing-webhook@example.com", "password": "strong-password"},
    ).json()
    user_id = auth["user"]["id"]
    monkeypatch.setattr(main.billing_service, "construct_webhook_event", lambda payload, signature: json.loads(payload))
    event = {
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_test",
                "customer": "cus_test",
                "status": "active",
                "current_period_end": 1893456000,
                "metadata": {"user_id": user_id, "plan": "pro"},
                "items": {"data": [{"price": {"id": "price_pro"}}]},
            }
        },
    }

    webhook = client.post("/billing/stripe/webhook", json=event)
    billing = client.get("/billing/me", headers={"Authorization": f"Bearer {auth['access_token']}"})

    assert webhook.status_code == 200
    assert webhook.json()["handled"] is True
    assert billing.json()["account"]["stripe_subscription_id"] == "sub_test"
    assert billing.json()["entitlements"]["plan"] == "pro"


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


def test_admin_routes_require_admin_key_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ADMIN_API_KEY", "local-admin-secret")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    missing = client.get("/admin/overview")
    wrong = client.get("/admin/overview", headers={"X-Admin-Key": "wrong"})
    ok = client.get("/admin/overview", headers={"X-Admin-Key": "local-admin-secret"})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert ok.status_code == 200
    assert ok.json()["users"]["count"] == 0


def test_admin_projects_and_users_cross_user_boundaries(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ENABLE_USER_AUTH", "true")
    monkeypatch.setenv("ADMIN_API_KEY", "local-admin-secret")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    alice = client.post(
        "/auth/register",
        json={"email": "admin-alice@example.com", "password": "strong-password"},
    ).json()["access_token"]
    bob = client.post(
        "/auth/register",
        json={"email": "admin-bob@example.com", "password": "strong-password"},
    ).json()["access_token"]
    alice_headers = {"Authorization": f"Bearer {alice}"}
    bob_headers = {"Authorization": f"Bearer {bob}"}

    alice_project = client.post("/projects", json={"topic": "Admin Alice project"}, headers=alice_headers)
    bob_project = client.post("/projects", json={"topic": "Admin Bob project"}, headers=bob_headers)
    admin_headers = {"X-Admin-Key": "local-admin-secret"}
    projects = client.get("/admin/projects", headers=admin_headers)
    users = client.get("/admin/users", headers=admin_headers)

    assert alice_project.status_code == 200
    assert bob_project.status_code == 200
    assert projects.status_code == 200
    assert projects.headers["x-total-count"] == "2"
    assert {project["id"] for project in projects.json()} == {alice_project.json()["id"], bob_project.json()["id"]}
    assert users.status_code == 200
    assert users.headers["x-total-count"] == "2"


def test_admin_support_ticket_workflow_records_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ENABLE_USER_AUTH", "true")
    monkeypatch.setenv("ADMIN_API_KEY", "local-admin-secret")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    token = client.post(
        "/auth/register",
        json={"email": "support-user@example.com", "password": "strong-password"},
    ).json()["access_token"]
    created = client.post(
        "/projects",
        json={"topic": "Support ticket project"},
        headers={"Authorization": f"Bearer {token}"},
    )
    admin_headers = {"X-Admin-Key": "local-admin-secret"}
    ticket = client.post(
        "/admin/support/tickets",
        headers=admin_headers,
        json={
            "subject": "Render job failed",
            "message": "Customer reports a failed render",
            "user_id": created.json()["owner_id"],
            "project_id": created.json()["id"],
            "priority": "high",
            "tags": [" Render ", "failure"],
        },
    )
    ticket_id = ticket.json()["id"]
    updated = client.patch(
        f"/admin/support/tickets/{ticket_id}",
        headers=admin_headers,
        json={"status": "pending", "assignee": "support-lead", "tags": ["render", "triage"]},
    )
    noted = client.post(
        f"/admin/support/tickets/{ticket_id}/notes",
        headers=admin_headers,
        json={"body": "Asked user for render logs.", "internal": True},
    )
    listed = client.get("/admin/support/tickets?status=pending", headers=admin_headers)
    audit = client.get(f"/admin/audit/events?resource_type=support_ticket&resource_id={ticket_id}", headers=admin_headers)
    overview = client.get("/admin/overview", headers=admin_headers)

    assert ticket.status_code == 200
    assert ticket.json()["priority"] == "high"
    assert ticket.json()["tags"] == ["render", "failure"]
    assert updated.status_code == 200
    assert updated.json()["status"] == "pending"
    assert updated.json()["assignee"] == "support-lead"
    assert noted.status_code == 200
    assert len(noted.json()["notes"]) == 2
    assert listed.status_code == 200
    assert listed.headers["x-total-count"] == "1"
    assert listed.json()[0]["id"] == ticket_id
    assert {event["action"] for event in audit.json()} >= {
        "support.ticket.create",
        "support.ticket.update",
        "support.ticket.note",
    }
    assert overview.json()["support"]["ticket_count"] == 1


def test_observability_metrics_collects_requests(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("JSON_LOGS", "true")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    health = client.get("/health", headers={"X-Request-ID": "req_test_observability"})
    assert health.status_code == 200
    assert health.headers["x-request-id"] == "req_test_observability"
    response = client.get("/observability/metrics")
    diagnostics = client.get("/diagnostics")

    assert response.status_code == 200
    metrics = response.json()["metrics"]
    assert metrics["total_requests"] >= 1
    assert metrics["by_status"]["200"] >= 1
    assert metrics["by_path"]["GET /health"] >= 1
    prometheus = client.get("/observability/metrics/prometheus")
    assert prometheus.status_code == 200
    assert "ai_video_studio_requests_total" in prometheus.text
    assert 'ai_video_studio_requests_by_status_total{status="200"}' in prometheus.text
    assert diagnostics.json()["logging"] == {"level": "DEBUG", "json_logs": True}


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


def test_api_project_manifest_reports_avatar_readiness(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)

    created = client.post(
        "/projects",
        json={
            "topic": "AI-аватар проверяет готовность HeyGen MP4",
            "style": "ai_news_avatar",
            "avatar_enabled": True,
        },
    )
    assert created.status_code == 200
    project_id = created.json()["id"]
    project = main.pipeline.generate_script(project_id)
    avatar_dir = main.store.project_dir(project_id) / "assets" / "avatar"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    avatar_scenes = [scene for scene in project.scenes if scene.avatar_visible and scene.visual_type in {"avatar_fullscreen", "avatar_pip", "screen_demo", "cta"}]
    for scene in avatar_scenes:
        avatar_path = avatar_dir / f"scene_{scene.order:03d}_heygen.mp4"
        avatar_path.write_bytes(b"fake mp4")
        scene.avatar_video_id = f"vid_{scene.order:03d}"
        scene.avatar_video_status = "completed"
        scene.avatar_video_url = f"https://video.local/{scene.order:03d}.mp4"
        scene.avatar_video_path = str(avatar_path)
    main.store.save(project)

    response = client.get(f"/projects/{project_id}/manifest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["counts"]["avatar_scenes"] == len(avatar_scenes)
    assert payload["counts"]["avatar_videos_submitted"] == len(avatar_scenes)
    assert payload["counts"]["avatar_videos_ready_remote"] == len(avatar_scenes)
    assert payload["counts"]["avatar_videos_downloaded"] == len(avatar_scenes)
    assert payload["counts"]["avatar_videos_failed"] == 0
    assert payload["readiness"]["avatars"] is True


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
    providers = client.get("/providers")
    assert providers.status_code == 200
    assert providers.json()["project_storage"]["backend"] == "local"
    assert providers.json()["jobs"]["storage"]["backend"] == "local"
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


def test_job_runner_can_enqueue_without_api_execution_and_worker_drains_queue(tmp_path):
    settings = make_settings(tmp_path)
    settings = Settings(
        **{
            **settings.__dict__,
            "run_jobs_inline": False,
            "execute_jobs_in_api": False,
        }
    )
    store = ProjectStore(settings)
    pipeline = make_pipeline(settings, store)
    job_store = JobStore(settings)
    runner = JobRunner(settings, pipeline, job_store)
    project = store.create_project(ProjectCreate(topic="External worker job execution"))

    queued = runner.start(project.id, JobType.generate_script)

    assert queued.status == JobStatus.queued
    assert any(event["event"] == "queued_for_external_worker" for event in queued.events)
    assert store.get(project.id).status == ProjectStatus.queued

    completed = runner.run_next_queued()

    assert completed is not None
    assert completed.id == queued.id
    assert completed.status == JobStatus.completed
    assert store.get(project.id).status == ProjectStatus.script_ready


def test_worker_cli_help_loads(tmp_path):
    result = subprocess.run(
        [sys.executable, "backend/job_worker.py", "--help"],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert "queued AI Video Studio jobs" in result.stdout
    assert "--auto-avatar-sync" in result.stdout


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
