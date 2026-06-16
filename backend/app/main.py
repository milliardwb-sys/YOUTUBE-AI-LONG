from __future__ import annotations

import logging
import time
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from app.config import get_settings
from app.models import JobType, Project, ProjectCreate, ProjectUpdate, SceneCreate, ScenePatch, SceneReorder
from app.pipeline import VideoPipeline
from app.services.avatar_service import AvatarService
from app.services.compliance_service import ComplianceService
from app.services.job_service import JobNotCancellableError, JobNotFoundError, JobNotRetryableError, JobRunner, JobStore
from app.services.render_service import RenderService
from app.services.script_service import ScriptService
from app.services.source_service import SourceService
from app.services.visual_service import VisualService
from app.services.voice_service import VoiceService
from app.storage import InvalidSceneOrderError, ProjectNotFoundError, ProjectStore, SceneNotFoundError
from app.models import ProjectStatus
from app.utils.security import InvalidIdentifierError, UnsafePathError, ensure_within_directory

settings = get_settings()
logger = logging.getLogger("ai_video_studio.api")
store = ProjectStore(settings)
pipeline = VideoPipeline(
    store=store,
    compliance=ComplianceService(),
    script=ScriptService(settings),
    sources=SourceService(settings),
    visuals=VisualService(settings),
    voice=VoiceService(settings),
    avatar=AvatarService(),
    render=RenderService(settings),
)
job_store = JobStore(settings)
job_runner = JobRunner(settings, pipeline, job_store)

app = FastAPI(
    title="AI Video Studio MVP API",
    version="0.4.0",
    description="MVP backend: topic -> jobs -> script provider -> sources -> voice provider -> slides -> MP4.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials="*" not in settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    started = time.perf_counter()
    request_id = request.headers.get("x-request-id") or f"req_{uuid4().hex[:12]}"
    public_paths = {"/health", "/ready", "/providers", "/openapi.json"}
    is_docs_path = request.url.path in {"/docs", "/redoc"} or request.url.path.startswith("/docs/")
    is_public_path = request.url.path in public_paths or is_docs_path
    if settings.app_env not in {"local", "test", "dev", "development"} and not settings.api_key and not is_public_path:
        response = JSONResponse(
            status_code=403,
            content={"detail": "API_KEY must be configured for non-local environments"},
        )
        response.headers["x-request-id"] = request_id
        return response
    if settings.api_key and not is_public_path:
        if request.headers.get("x-api-key") != settings.api_key:
            response = JSONResponse(status_code=401, content={"detail": "Invalid or missing X-API-Key"})
            response.headers["x-request-id"] = request_id
            return response
    response = await call_next(request)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    response.headers["x-request-id"] = request_id
    logger.info(
        "request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "elapsed_ms": elapsed_ms,
        },
    )
    return response


def _get_project_or_404(project_id: str) -> Project:
    try:
        return store.get(project_id)
    except (InvalidIdentifierError, UnsafePathError):
        raise HTTPException(status_code=404, detail="Project not found") from None
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None


def _with_file_urls(project: Project) -> dict:
    payload = project.model_dump(mode="json")

    def public_url(path_value: str | None) -> str | None:
        if not path_value:
            return None
        try:
            path = ensure_within_directory(settings.data_dir, Path(path_value))
            relative = path.relative_to(settings.data_dir)
        except (OSError, ValueError):
            return None
        return f"{settings.public_base_url}/files/{relative.as_posix()}"

    result = payload.get("result", {})
    for key in [
        "final_video_path",
        "subtitles_path",
        "captions_vtt_path",
        "description_path",
        "sources_path",
        "storyboard_path",
        "thumbnail_prompt_path",
        "thumbnail_path",
        "title_options_path",
        "youtube_metadata_path",
        "quality_report_path",
        "voice_manifest_path",
        "render_manifest_path",
        "export_package_path",
    ]:
        result[key.replace("_path", "_url")] = public_url(result.get(key))
    payload["result"] = result

    for scene in payload.get("scenes", []):
        scene["visual_url"] = public_url(scene.get("visual_path"))
        scene["audio_url"] = public_url(scene.get("audio_path"))
    for source in payload.get("sources", []):
        source["screenshot_url"] = public_url(source.get("screenshot_path"))
    return payload


def _job_or_404(job_id: str) -> dict:
    try:
        return job_store.get(job_id).model_dump(mode="json")
    except (InvalidIdentifierError, UnsafePathError):
        raise HTTPException(status_code=404, detail="Job not found") from None
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail="Job not found") from None


def _sync_pipeline_response(project: Project) -> dict:
    if project.status == ProjectStatus.failed:
        status_code = 400 if project.current_step == "compliance_failed" else 500
        if project.current_step == "precondition_failed":
            status_code = 409
        raise HTTPException(
            status_code=status_code,
            detail={
                "project_id": project.id,
                "status": project.status,
                "current_step": project.current_step,
                "error": project.error or "Pipeline failed",
            },
        )
    return _with_file_urls(project)


@app.get("/health")
def health() -> dict[str, str | bool | int]:
    return {
        "status": "ok",
        "version": "0.4.0",
        "env": settings.app_env,
        "browser_screenshots": settings.enable_browser_screenshots,
        "openai_configured": bool(settings.openai_api_key),
        "run_jobs_inline": settings.run_jobs_inline,
        "job_workers": settings.job_workers,
        "auth_required": bool(settings.api_key),
        "auth_configured_for_env": bool(settings.api_key) or settings.app_env in {"local", "test", "dev", "development"},
    }


@app.get("/ready")
def ready() -> dict[str, str | bool]:
    ffmpeg_available = bool(pipeline.render_service.resolve_ffmpeg_bin())
    data_dir_writable = _data_dir_is_writable()
    return {
        "status": "ready" if ffmpeg_available and data_dir_writable else "not_ready",
        "ffmpeg_available": ffmpeg_available,
        "data_dir_writable": data_dir_writable,
    }


@app.get("/diagnostics")
def diagnostics() -> dict:
    ffmpeg_bin = pipeline.render_service.resolve_ffmpeg_bin()
    return {
        "status": "ok" if ffmpeg_bin and _data_dir_is_writable() else "needs_attention",
        "version": "0.4.0",
        "env": settings.app_env,
        "data_dir": {
            "path": settings.data_dir.as_posix(),
            "exists": settings.data_dir.exists(),
            "writable": _data_dir_is_writable(),
        },
        "ffmpeg": {
            "configured": settings.ffmpeg_bin,
            "resolved": ffmpeg_bin,
            "available": bool(ffmpeg_bin),
        },
        "auth_required": bool(settings.api_key),
        "auth_configured_for_env": bool(settings.api_key) or settings.app_env in {"local", "test", "dev", "development"},
        "cors_origins": settings.cors_origins,
        "browser_screenshots": {
            "enabled": settings.enable_browser_screenshots,
            "allow_private_source_urls": settings.allow_private_source_urls,
            "allow_unsafe_http_sources": settings.allow_unsafe_http_sources,
        },
        "providers": {
            "openai_configured": bool(settings.openai_api_key),
            "script_default": settings.default_script_provider,
            "voice_default": settings.default_voice_provider,
        },
        "jobs": {
            "run_inline": settings.run_jobs_inline,
            "workers": settings.job_workers,
        },
    }


def _data_dir_is_writable() -> bool:
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        probe = settings.data_dir / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


@app.get("/providers")
def providers() -> dict:
    return {
        "script": {
            "available": ["template", "openai"],
            "default": settings.default_script_provider,
            "openai_configured": bool(settings.openai_api_key),
            "openai_model": settings.openai_model,
        },
        "voice": {
            "available": ["placeholder", "openai"],
            "default": settings.default_voice_provider,
            "openai_configured": bool(settings.openai_api_key),
            "openai_tts_model": settings.openai_tts_model,
            "openai_tts_voice": settings.openai_tts_voice,
        },
        "screenshots": {
            "browser_enabled": settings.enable_browser_screenshots,
            "timeout_ms": settings.browser_timeout_ms,
        },
        "jobs": {
            "available": [item.value for item in JobType],
            "run_inline": settings.run_jobs_inline,
            "workers": settings.job_workers,
        },
    }


@app.post("/maintenance/cleanup")
def cleanup() -> dict:
    return {
        **store.cleanup_old_projects(),
        **job_store.cleanup_old_jobs(),
        "retention_days": settings.cleanup_retention_days,
    }


@app.post("/projects")
def create_project(payload: ProjectCreate) -> dict:
    project = store.create_project(payload)
    return _with_file_urls(project)


@app.get("/projects")
def list_projects() -> list[dict]:
    return [_with_file_urls(project) for project in store.list_projects()]


@app.get("/projects/{project_id}")
def get_project(project_id: str) -> dict:
    return _with_file_urls(_get_project_or_404(project_id))


@app.patch("/projects/{project_id}")
def update_project(project_id: str, payload: ProjectUpdate) -> dict:
    _get_project_or_404(project_id)
    return _with_file_urls(store.update_project(project_id, payload))


@app.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str) -> Response:
    _get_project_or_404(project_id)
    store.delete_project(project_id)
    return Response(status_code=204)


@app.post("/projects/{project_id}/duplicate")
def duplicate_project(project_id: str) -> dict:
    _get_project_or_404(project_id)
    return _with_file_urls(store.duplicate_project(project_id))


@app.post("/projects/{project_id}/generate-script")
def generate_script(project_id: str) -> dict:
    _get_project_or_404(project_id)
    return _sync_pipeline_response(pipeline.generate_script(project_id))


@app.post("/projects/{project_id}/collect-sources")
def collect_sources(project_id: str) -> dict:
    _get_project_or_404(project_id)
    return _sync_pipeline_response(pipeline.collect_sources(project_id))


@app.post("/projects/{project_id}/generate-slides")
def generate_slides(project_id: str) -> dict:
    _get_project_or_404(project_id)
    return _sync_pipeline_response(pipeline.generate_slides(project_id))


@app.post("/projects/{project_id}/generate-voice")
def generate_voice(project_id: str) -> dict:
    _get_project_or_404(project_id)
    return _sync_pipeline_response(pipeline.generate_voice(project_id))


@app.post("/projects/{project_id}/prepare-avatar")
def prepare_avatar(project_id: str) -> dict:
    _get_project_or_404(project_id)
    return _sync_pipeline_response(pipeline.prepare_avatar(project_id))


@app.post("/projects/{project_id}/render")
def render(project_id: str) -> dict:
    _get_project_or_404(project_id)
    return _sync_pipeline_response(pipeline.render(project_id))


@app.post("/projects/{project_id}/generate-all")
def generate_all(project_id: str) -> dict:
    _get_project_or_404(project_id)
    return _sync_pipeline_response(pipeline.generate_all(project_id))


@app.post("/projects/{project_id}/jobs/{job_type}")
def start_project_job(project_id: str, job_type: JobType) -> dict:
    _get_project_or_404(project_id)
    return job_runner.start(project_id, job_type).model_dump(mode="json")


@app.post("/projects/{project_id}/generate-all-queued")
def generate_all_queued(project_id: str) -> dict:
    _get_project_or_404(project_id)
    return job_runner.start(project_id, JobType.generate_all).model_dump(mode="json")


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    return _job_or_404(job_id)


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    try:
        return job_runner.cancel(job_id).model_dump(mode="json")
    except (InvalidIdentifierError, UnsafePathError):
        raise HTTPException(status_code=404, detail="Job not found") from None
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail="Job not found") from None
    except JobNotCancellableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post("/jobs/{job_id}/retry")
def retry_job(job_id: str) -> dict:
    try:
        return job_runner.retry(job_id).model_dump(mode="json")
    except (InvalidIdentifierError, UnsafePathError):
        raise HTTPException(status_code=404, detail="Job not found") from None
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail="Job not found") from None
    except JobNotRetryableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.get("/jobs/{job_id}/events")
def get_job_events(job_id: str) -> list[dict]:
    return _job_or_404(job_id).get("events", [])


@app.get("/projects/{project_id}/jobs")
def list_project_jobs(project_id: str) -> list[dict]:
    _get_project_or_404(project_id)
    return [job.model_dump(mode="json") for job in job_store.list_for_project(project_id)]


@app.patch("/projects/{project_id}/scenes/{scene_id}")
def patch_scene(project_id: str, scene_id: str, payload: ScenePatch) -> dict:
    _get_project_or_404(project_id)
    try:
        return _with_file_urls(store.patch_scene(project_id, scene_id, payload))
    except SceneNotFoundError:
        raise HTTPException(status_code=404, detail="Scene not found") from None


@app.post("/projects/{project_id}/scenes")
def insert_scene(project_id: str, payload: SceneCreate) -> dict:
    _get_project_or_404(project_id)
    try:
        return _with_file_urls(store.insert_scene(project_id, payload))
    except SceneNotFoundError:
        raise HTTPException(status_code=404, detail="Scene not found") from None


@app.delete("/projects/{project_id}/scenes/{scene_id}")
def delete_scene(project_id: str, scene_id: str) -> dict:
    _get_project_or_404(project_id)
    try:
        return _with_file_urls(store.delete_scene(project_id, scene_id))
    except SceneNotFoundError:
        raise HTTPException(status_code=404, detail="Scene not found") from None


@app.post("/projects/{project_id}/scenes/reorder")
def reorder_scenes(project_id: str, payload: SceneReorder) -> dict:
    _get_project_or_404(project_id)
    try:
        return _with_file_urls(store.reorder_scenes(project_id, payload))
    except InvalidSceneOrderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.post("/projects/{project_id}/scenes/{scene_id}/regenerate-slide")
def regenerate_scene_slide(project_id: str, scene_id: str) -> dict:
    _get_project_or_404(project_id)
    try:
        return _sync_pipeline_response(pipeline.regenerate_scene_slide(project_id, scene_id))
    except SceneNotFoundError:
        raise HTTPException(status_code=404, detail="Scene not found") from None


@app.get("/files/{file_path:path}")
def get_file(file_path: str) -> FileResponse:
    try:
        path = ensure_within_directory(settings.data_dir, settings.data_dir / file_path)
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="File not found") from None
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)


@app.get("/projects/{project_id}/status")
def project_status(project_id: str) -> dict:
    project = _get_project_or_404(project_id)
    jobs = job_store.list_for_project(project_id)
    latest_job = jobs[0].model_dump(mode="json") if jobs else None
    return {
        "id": project.id,
        "status": project.status,
        "current_step": project.current_step,
        "error": project.error,
        "warnings": project.result.warnings,
        "scene_count": len(project.scenes),
        "source_count": len(project.sources),
        "latest_job": latest_job,
    }


@app.get("/projects/{project_id}/result")
def project_result(project_id: str) -> dict:
    project = _get_project_or_404(project_id)
    return _with_file_urls(project)["result"]
