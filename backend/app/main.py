from __future__ import annotations

import logging
import time
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from app.config import get_settings
from app.models import (
    JobStatus,
    JobType,
    PlatformUser,
    Project,
    ProjectCreate,
    ProjectJob,
    ProjectUpdate,
    SceneCreate,
    ScenePatch,
    SceneReorder,
    UserCreate,
    UserLogin,
)
from app.pipeline import VideoPipeline
from app.services.avatar_service import AvatarService
from app.services.auth_service import (
    AuthService,
    InvalidCredentialsError,
    SessionNotFoundError,
    UserAlreadyExistsError,
)
from app.services.audit_log_service import AuditLogService
from app.services.backup_service import BackupNotFoundError, BackupService, InvalidBackupError
from app.services.compliance_service import ComplianceService
from app.services.job_service import JobNotCancellableError, JobNotFoundError, JobNotRetryableError, JobRunner, JobStore
from app.services.idempotency_service import (
    IdempotencyConflictError,
    IdempotencyRecord,
    IdempotencyStore,
    InvalidIdempotencyKeyError,
)
from app.services.render_service import RenderService
from app.services.script_service import ScriptService
from app.services.usage_service import UsageService
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
auth_service = AuthService(settings)
idempotency_store = IdempotencyStore(settings)
audit_log = AuditLogService(settings)
usage_service = UsageService(settings)
backup_service = BackupService(settings)
app_started_at = time.time()
rate_limit_lock = Lock()
rate_limit_windows: dict[str, tuple[int, int]] = {}
metrics_lock = Lock()
request_metrics: dict[str, object] = {
    "total_requests": 0,
    "total_elapsed_ms": 0,
    "max_elapsed_ms": 0,
    "by_status": {},
    "by_path": {},
}

app = FastAPI(
    title="AI Video Studio MVP API",
    version="0.4.0",
    description="MVP backend: topic -> jobs -> script provider -> sources -> voice provider -> slides -> MP4.",
)

RESULT_ARTIFACT_KEYS = [
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
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials="*" not in settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return _error_response(
        status_code=exc.status_code,
        detail=exc.detail,
        request_id=getattr(request.state, "request_id", None),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _error_response(
        status_code=422,
        detail=exc.errors(),
        request_id=getattr(request.state, "request_id", None),
    )


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    started = time.perf_counter()
    request_id = request.headers.get("x-request-id") or f"req_{uuid4().hex[:12]}"
    request.state.request_id = request_id
    if _request_body_is_too_large(request):
        return _error_response(413, "Request body too large", request_id)
    public_paths = {"/health", "/ready", "/providers", "/openapi.json", "/auth/register", "/auth/login"}
    is_docs_path = request.url.path in {"/docs", "/redoc"} or request.url.path.startswith("/docs/")
    is_public_path = request.url.path in public_paths or is_docs_path
    if settings.app_env not in {"local", "test", "dev", "development"} and not settings.api_key and not is_public_path:
        return _error_response(403, "API_KEY must be configured for non-local environments", request_id)
    if settings.api_key and not is_public_path:
        if request.headers.get("x-api-key") != settings.api_key:
            return _error_response(401, "Invalid or missing X-API-Key", request_id)
    rate_limit_headers = _check_rate_limit(request)
    if rate_limit_headers is None:
        return _error_response(
            429,
            "Rate limit exceeded",
            request_id,
            headers={
                "retry-after": "60",
                "x-ratelimit-limit": str(settings.rate_limit_requests_per_minute),
                "x-ratelimit-remaining": "0",
            },
        )
    response = await call_next(request)
    for header, value in rate_limit_headers.items():
        response.headers[header] = value
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    _record_request_metric(request.method, request.url.path, response.status_code, elapsed_ms)
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


def _record_request_metric(method: str, path: str, status_code: int, elapsed_ms: int) -> None:
    status_key = str(status_code)
    path_key = f"{method.upper()} {path}"
    with metrics_lock:
        request_metrics["total_requests"] = int(request_metrics["total_requests"]) + 1
        request_metrics["total_elapsed_ms"] = int(request_metrics["total_elapsed_ms"]) + elapsed_ms
        request_metrics["max_elapsed_ms"] = max(int(request_metrics["max_elapsed_ms"]), elapsed_ms)
        by_status = request_metrics["by_status"]
        by_path = request_metrics["by_path"]
        if isinstance(by_status, dict):
            by_status[status_key] = int(by_status.get(status_key, 0)) + 1
        if isinstance(by_path, dict):
            by_path[path_key] = int(by_path.get(path_key, 0)) + 1


def _metrics_snapshot() -> dict:
    with metrics_lock:
        total = int(request_metrics["total_requests"])
        total_elapsed = int(request_metrics["total_elapsed_ms"])
        by_status = dict(request_metrics["by_status"]) if isinstance(request_metrics["by_status"], dict) else {}
        by_path = dict(request_metrics["by_path"]) if isinstance(request_metrics["by_path"], dict) else {}
        return {
            "uptime_seconds": int(time.time() - app_started_at),
            "total_requests": total,
            "average_elapsed_ms": round(total_elapsed / total, 2) if total else 0,
            "max_elapsed_ms": int(request_metrics["max_elapsed_ms"]),
            "by_status": by_status,
            "by_path": dict(sorted(by_path.items(), key=lambda item: item[1], reverse=True)[:50]),
        }


def _error_response(
    status_code: int,
    detail: object,
    request_id: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    if isinstance(detail, str):
        message = detail
    elif isinstance(detail, list):
        message = "Validation error"
    else:
        message = "Request failed"
    content = {
        "detail": jsonable_encoder(detail),
        "error": {
            "status_code": status_code,
            "message": message,
            "request_id": request_id,
        },
    }
    response = JSONResponse(status_code=status_code, content=content, headers=headers)
    if request_id:
        response.headers["x-request-id"] = request_id
    return response


def _rate_limit_key(request: Request) -> str:
    if request.headers.get("x-api-key"):
        return f"api:{request.headers['x-api-key']}"
    if request.client and request.client.host:
        return f"ip:{request.client.host}"
    return "ip:unknown"


def _request_body_is_too_large(request: Request) -> bool:
    limit = settings.max_request_body_bytes
    if limit <= 0:
        return False
    content_length = request.headers.get("content-length")
    if not content_length:
        return False
    try:
        return int(content_length) > limit
    except ValueError:
        return False


def _check_rate_limit(request: Request) -> dict[str, str] | None:
    limit = settings.rate_limit_requests_per_minute
    if limit <= 0:
        return {}
    now = int(time.time())
    window = now // 60
    key = _rate_limit_key(request)
    with rate_limit_lock:
        current_window, count = rate_limit_windows.get(key, (window, 0))
        if current_window != window:
            current_window, count = window, 0
        if count >= limit:
            return None
        count += 1
        rate_limit_windows[key] = (current_window, count)
        remaining = max(0, limit - count)
    reset = ((window + 1) * 60) - now
    return {
        "x-ratelimit-limit": str(limit),
        "x-ratelimit-remaining": str(remaining),
        "x-ratelimit-reset": str(reset),
    }


def _auth_enabled() -> bool:
    return settings.enable_user_auth


def _bearer_token(request: Request) -> str | None:
    value = request.headers.get("authorization") or ""
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _current_user(request: Request) -> PlatformUser | None:
    token = _bearer_token(request)
    if not token:
        if _auth_enabled():
            raise HTTPException(status_code=401, detail="Missing bearer token")
        return None
    try:
        return auth_service.get_user_by_token(token)
    except (InvalidCredentialsError, SessionNotFoundError):
        raise HTTPException(status_code=401, detail="Invalid or expired bearer token") from None


def _user_scope(user: PlatformUser | None) -> str:
    return user.id if user else "public"


def _idempotency_key(request: Request) -> str | None:
    raw_key = request.headers.get("idempotency-key")
    if not raw_key:
        return None
    try:
        return idempotency_store.normalize_key(raw_key)
    except InvalidIdempotencyKeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


def _idempotency_record(key: str, scope: str, request_hash: str) -> IdempotencyRecord | None:
    try:
        return idempotency_store.get(key=key, scope=scope, request_hash=request_hash)
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


def _replay_project_record(
    record: IdempotencyRecord | None,
    *,
    key: str,
    scope: str,
    request: Request,
    response: Response,
) -> dict | None:
    if record is None or record.resource_type != "project":
        return None
    try:
        project = _get_project_or_404(record.resource_id, request)
    except HTTPException:
        idempotency_store.delete(key=key, scope=scope)
        return None
    response.headers["x-idempotent-replay"] = "true"
    return _with_file_urls(project)


def _replay_job_record(
    record: IdempotencyRecord | None,
    *,
    key: str,
    scope: str,
    request: Request,
    response: Response,
) -> dict | None:
    if record is None or record.resource_type != "job":
        return None
    try:
        job = _get_job_or_404(record.resource_id, request)
    except HTTPException:
        idempotency_store.delete(key=key, scope=scope)
        return None
    response.headers["x-idempotent-replay"] = "true"
    return job.model_dump(mode="json")


def _set_pagination_headers(response: Response, *, total: int, limit: int, offset: int) -> None:
    response.headers["x-total-count"] = str(total)
    response.headers["x-limit"] = str(limit)
    response.headers["x-offset"] = str(offset)


def _actor_id(user: PlatformUser | None) -> str | None:
    return user.id if user else None


def _project_owner_scope(user: PlatformUser | None) -> str | None:
    return user.id if user else None


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _audit(
    request: Request,
    action: str,
    *,
    actor_id: str | None = None,
    resource_type: str = "system",
    resource_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    audit_log.record(
        action,
        actor_id=actor_id,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=_request_id(request),
        metadata=metadata,
    )


def _active_job_count_for_user(user: PlatformUser | None) -> int:
    actor_id = _actor_id(user)
    count = 0
    for job in job_store.list_all():
        if job.status not in {JobStatus.queued, JobStatus.running}:
            continue
        if actor_id is not None and job.owner_id != actor_id:
            continue
        if actor_id is None and _auth_enabled():
            continue
        count += 1
    return count


def _project_count_for_user(user: PlatformUser | None) -> int:
    return len(store.list_projects(owner_id=_project_owner_scope(user)))


def _usage_limits(user: PlatformUser | None) -> dict[str, int]:
    return {
        "max_projects": settings.usage_max_projects_per_user,
        "max_active_jobs": settings.usage_max_active_jobs_per_user,
        "current_projects": _project_count_for_user(user),
        "current_active_jobs": _active_job_count_for_user(user),
    }


def _enforce_project_quota(user: PlatformUser | None) -> None:
    limit = settings.usage_max_projects_per_user
    if limit <= 0:
        return
    current = _project_count_for_user(user)
    if current >= limit:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "project_quota_exceeded",
                "limit": limit,
                "current": current,
                "message": "Project quota exceeded",
            },
        )


def _enforce_active_job_quota(user: PlatformUser | None) -> None:
    limit = settings.usage_max_active_jobs_per_user
    if limit <= 0:
        return
    current = _active_job_count_for_user(user)
    if current >= limit:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "active_job_quota_exceeded",
                "limit": limit,
                "current": current,
                "message": "Active job quota exceeded",
            },
        )


def _estimate_job_cost_cents(project: Project, job_type: JobType) -> int:
    duration = max(1, project.duration_minutes)
    if job_type == JobType.generate_script:
        return settings.usage_llm_job_cost_cents if project.script_provider.value == "openai" else 0
    if job_type == JobType.generate_voice:
        return settings.usage_tts_cost_cents_per_minute * duration if project.voice_provider.value == "openai" else 0
    if job_type == JobType.render:
        return settings.usage_render_cost_cents_per_minute * duration
    if job_type == JobType.generate_all:
        cost = settings.usage_render_cost_cents_per_minute * duration
        if project.script_provider.value == "openai":
            cost += settings.usage_llm_job_cost_cents
        if project.voice_provider.value == "openai":
            cost += settings.usage_tts_cost_cents_per_minute * duration
        return cost
    return 0


def _project_is_visible_to_user(project: Project, user: PlatformUser | None) -> bool:
    if not _auth_enabled():
        return True
    if user is None:
        return False
    return project.owner_id == user.id


def _job_is_visible_to_user(job: ProjectJob, user: PlatformUser | None) -> bool:
    if not _auth_enabled():
        return True
    if user is None:
        return False
    if job.owner_id is not None:
        return job.owner_id == user.id
    try:
        project = store.get(job.project_id)
    except Exception:
        return False
    return project.owner_id == user.id


def _get_project_or_404(project_id: str, request: Request | None = None) -> Project:
    try:
        project = store.get(project_id)
    except (InvalidIdentifierError, UnsafePathError):
        raise HTTPException(status_code=404, detail="Project not found") from None
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    user = _current_user(request) if request is not None else None
    if not _project_is_visible_to_user(project, user):
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _with_file_urls(project: Project) -> dict:
    payload = project.model_dump(mode="json")

    result = payload.get("result", {})
    for key in RESULT_ARTIFACT_KEYS:
        result[key.replace("_path", "_url")] = _public_file_url(result.get(key))
    payload["result"] = result

    for scene in payload.get("scenes", []):
        scene["visual_url"] = _public_file_url(scene.get("visual_path"))
        scene["audio_url"] = _public_file_url(scene.get("audio_path"))
    for source in payload.get("sources", []):
        source["screenshot_url"] = _public_file_url(source.get("screenshot_path"))
    return payload


def _public_file_url(path_value: str | None) -> str | None:
    if not path_value:
        return None
    try:
        path = ensure_within_directory(settings.data_dir, Path(path_value))
        relative = path.relative_to(settings.data_dir)
    except (OSError, ValueError):
        return None
    return f"{settings.public_base_url}/files/{relative.as_posix()}"


def _artifact_entry(key: str, path_value: str | None) -> dict:
    exists = False
    size_bytes = 0
    if path_value:
        try:
            path = ensure_within_directory(settings.data_dir, Path(path_value))
            exists = path.is_file()
            size_bytes = path.stat().st_size if exists else 0
        except (OSError, ValueError):
            exists = False
            size_bytes = 0
    return {
        "key": key.replace("_path", ""),
        "path": path_value,
        "url": _public_file_url(path_value),
        "exists": exists,
        "size_bytes": size_bytes,
    }


def _project_manifest(project: Project) -> dict:
    result = project.result.model_dump(mode="json")
    artifacts = [_artifact_entry(key, result.get(key)) for key in RESULT_ARTIFACT_KEYS]
    missing_artifacts = [item["key"] for item in artifacts if item["path"] and not item["exists"]]
    expected_artifacts = [item["key"] for item in artifacts if item["path"]]
    ready_artifacts = [item["key"] for item in artifacts if item["exists"]]
    scenes_with_visuals = sum(1 for scene in project.scenes if scene.visual_path)
    scenes_with_audio = sum(1 for scene in project.scenes if scene.audio_path)
    captured_sources = sum(1 for source in project.sources if source.screenshot_path)
    has_render_output = bool(project.result.final_video_path and _artifact_entry("final_video_path", project.result.final_video_path)["exists"])
    has_export_package = bool(project.result.export_package_path and _artifact_entry("export_package_path", project.result.export_package_path)["exists"])
    return {
        "project_id": project.id,
        "topic": project.topic,
        "status": project.status,
        "current_step": project.current_step,
        "error": project.error,
        "warnings": project.result.warnings,
        "counts": {
            "scenes": len(project.scenes),
            "sources": len(project.sources),
            "scenes_with_visuals": scenes_with_visuals,
            "scenes_with_audio": scenes_with_audio,
            "sources_with_screenshots": captured_sources,
            "expected_artifacts": len(expected_artifacts),
            "ready_artifacts": len(ready_artifacts),
            "missing_artifacts": len(missing_artifacts),
        },
        "readiness": {
            "script": bool(project.scenes),
            "sources": bool(project.sources),
            "visuals": bool(project.scenes) and scenes_with_visuals == len(project.scenes),
            "voice": bool(project.scenes) and scenes_with_audio == len(project.scenes),
            "render": has_render_output,
            "export_package": has_export_package,
            "publish_ready": project.status == ProjectStatus.completed and has_render_output and has_export_package and not missing_artifacts,
        },
        "artifacts": artifacts,
        "missing_artifacts": missing_artifacts,
    }


def _get_job_or_404(job_id: str, request: Request | None = None) -> ProjectJob:
    try:
        job = job_store.get(job_id)
    except (InvalidIdentifierError, UnsafePathError):
        raise HTTPException(status_code=404, detail="Job not found") from None
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail="Job not found") from None
    user = _current_user(request) if request is not None else None
    if not _job_is_visible_to_user(job, user):
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _job_or_404(job_id: str, request: Request | None = None) -> dict:
    return _get_job_or_404(job_id, request).model_dump(mode="json")


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


def _start_project_job(project_id: str, job_type: JobType, request: Request, response: Response) -> dict:
    project = _get_project_or_404(project_id, request)
    user = _current_user(request)
    key = _idempotency_key(request)
    if key:
        scope = f"jobs:start:{project_id}:{job_type.value}:{project.owner_id or 'public'}"
        request_hash = idempotency_store.request_hash({"project_id": project_id, "job_type": job_type.value})
        record = _idempotency_record(key, scope, request_hash)
        replay = _replay_job_record(record, key=key, scope=scope, request=request, response=response)
        if replay is not None:
            return replay

    if job_store.active_for_project(project_id) is None:
        _enforce_active_job_quota(user)
    job = job_runner.start(project_id, job_type)
    if key:
        idempotency_store.save(
            key=key,
            scope=scope,
            request_hash=request_hash,
            resource_type="job",
            resource_id=job.id,
        )
        response.headers["x-idempotent-replay"] = "false"
    usage_service.record(
        "job.start",
        actor_id=_actor_id(user),
        resource_type="job",
        resource_id=job.id,
        units=1,
        estimated_cost_cents=_estimate_job_cost_cents(project, job_type),
        metadata={"project_id": project_id, "job_type": job_type.value},
    )
    _audit(
        request,
        "job.start",
        actor_id=project.owner_id,
        resource_type="job",
        resource_id=job.id,
        metadata={"project_id": project_id, "job_type": job_type.value},
    )
    return job.model_dump(mode="json")


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
        "render_timeout_seconds": settings.render_timeout_seconds,
        "auth_required": bool(settings.api_key),
        "user_auth_enabled": settings.enable_user_auth,
        "auth_configured_for_env": bool(settings.api_key) or settings.app_env in {"local", "test", "dev", "development"},
        "rate_limit_requests_per_minute": settings.rate_limit_requests_per_minute,
        "max_request_body_bytes": settings.max_request_body_bytes,
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
        "user_auth_enabled": settings.enable_user_auth,
        "auth_configured_for_env": bool(settings.api_key) or settings.app_env in {"local", "test", "dev", "development"},
        "rate_limit_requests_per_minute": settings.rate_limit_requests_per_minute,
        "max_request_body_bytes": settings.max_request_body_bytes,
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
            **job_store.stats(),
        },
        "render": {
            "timeout_seconds": settings.render_timeout_seconds,
        },
    }


@app.get("/observability/metrics")
def observability_metrics() -> dict:
    return {
        "status": "ok",
        "version": "0.4.0",
        "metrics": _metrics_snapshot(),
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


@app.post("/auth/register")
def register_user(payload: UserCreate, request: Request) -> dict:
    if not _auth_enabled():
        raise HTTPException(status_code=404, detail="User auth is disabled")
    try:
        token = auth_service.register(payload)
        _audit(request, "auth.register", actor_id=token.user.id, resource_type="user", resource_id=token.user.id)
        return token.model_dump(mode="json")
    except UserAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post("/auth/login")
def login_user(payload: UserLogin, request: Request) -> dict:
    if not _auth_enabled():
        raise HTTPException(status_code=404, detail="User auth is disabled")
    try:
        token = auth_service.login(payload)
        _audit(request, "auth.login", actor_id=token.user.id, resource_type="user", resource_id=token.user.id)
        return token.model_dump(mode="json")
    except InvalidCredentialsError:
        raise HTTPException(status_code=401, detail="Invalid email or password") from None


@app.get("/auth/me")
def auth_me(request: Request) -> dict:
    if not _auth_enabled():
        raise HTTPException(status_code=404, detail="User auth is disabled")
    user = _current_user(request)
    return user.public().model_dump(mode="json") if user else {}


@app.post("/auth/logout")
def logout_user(request: Request) -> dict:
    if not _auth_enabled():
        raise HTTPException(status_code=404, detail="User auth is disabled")
    user = _current_user(request)
    token = _bearer_token(request)
    revoked = auth_service.revoke_token(token or "")
    if user:
        _audit(request, "auth.logout", actor_id=user.id, resource_type="user", resource_id=user.id)
    return {"revoked": revoked}


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


@app.get("/stats")
def stats() -> dict:
    return {
        "status": "ok",
        "version": "0.4.0",
        "env": settings.app_env,
        "storage": store.stats(),
        "jobs": job_store.stats(),
    }


@app.post("/maintenance/cleanup")
def cleanup() -> dict:
    return {
        **store.cleanup_old_projects(),
        **job_store.cleanup_old_jobs(),
        **auth_service.cleanup_expired_sessions(),
        **idempotency_store.cleanup_old_records(),
        **audit_log.cleanup_old_events(),
        **usage_service.cleanup_old_events(),
        "retention_days": settings.cleanup_retention_days,
    }


@app.post("/maintenance/backups")
def create_backup() -> dict:
    return backup_service.create_backup()


@app.get("/maintenance/backups")
def list_backups() -> list[dict]:
    return backup_service.list_backups()


@app.get("/maintenance/backups/{backup_id}")
def download_backup(backup_id: str) -> FileResponse:
    try:
        return FileResponse(backup_service.backup_path(backup_id), media_type="application/zip", filename=backup_id)
    except InvalidBackupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except BackupNotFoundError:
        raise HTTPException(status_code=404, detail="Backup not found") from None


@app.post("/maintenance/backups/{backup_id}/restore-preview")
def restore_backup_preview(backup_id: str) -> dict:
    try:
        return backup_service.restore_preview(backup_id)
    except InvalidBackupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except BackupNotFoundError:
        raise HTTPException(status_code=404, detail="Backup not found") from None


@app.get("/audit/events")
def list_audit_events(
    request: Request,
    response: Response,
    resource_type: str | None = None,
    resource_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    user = _current_user(request)
    actor_id = user.id if _auth_enabled() and user else None
    events = audit_log.list_events(actor_id=actor_id, resource_type=resource_type, resource_id=resource_id)
    _set_pagination_headers(response, total=len(events), limit=limit, offset=offset)
    return [
        {
            "id": event.id,
            "action": event.action,
            "actor_id": event.actor_id,
            "resource_type": event.resource_type,
            "resource_id": event.resource_id,
            "request_id": event.request_id,
            "metadata": event.metadata,
            "created_at": event.created_at.isoformat(),
        }
        for event in events[offset : offset + limit]
    ]


@app.get("/usage/me")
def usage_me(request: Request) -> dict:
    user = _current_user(request)
    actor_id = _actor_id(user)
    return {
        "actor_id": actor_id,
        "limits": _usage_limits(user),
        "usage": usage_service.summary(actor_id=actor_id if _auth_enabled() else None),
        "cost_model": {
            "llm_job_cost_cents": settings.usage_llm_job_cost_cents,
            "tts_cost_cents_per_minute": settings.usage_tts_cost_cents_per_minute,
            "render_cost_cents_per_minute": settings.usage_render_cost_cents_per_minute,
        },
    }


@app.post("/projects")
def create_project(payload: ProjectCreate, request: Request, response: Response) -> dict:
    user = _current_user(request)
    key = _idempotency_key(request)
    if key:
        scope = f"projects:create:{_user_scope(user)}"
        request_hash = idempotency_store.request_hash(payload.model_dump(mode="json"))
        record = _idempotency_record(key, scope, request_hash)
        replay = _replay_project_record(record, key=key, scope=scope, request=request, response=response)
        if replay is not None:
            return replay
    _enforce_project_quota(user)
    project = store.create_project(payload, owner_id=user.id if user else None)
    if key:
        idempotency_store.save(
            key=key,
            scope=scope,
            request_hash=request_hash,
            resource_type="project",
            resource_id=project.id,
        )
        response.headers["x-idempotent-replay"] = "false"
    _audit(
        request,
        "project.create",
        actor_id=user.id if user else None,
        resource_type="project",
        resource_id=project.id,
        metadata={"topic": project.topic},
    )
    usage_service.record(
        "project.create",
        actor_id=_actor_id(user),
        resource_type="project",
        resource_id=project.id,
        units=1,
        estimated_cost_cents=0,
        metadata={"topic": project.topic},
    )
    return _with_file_urls(project)


@app.get("/projects")
def list_projects(
    request: Request,
    response: Response,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    user = _current_user(request)
    projects = store.list_projects(owner_id=user.id if user else None)
    _set_pagination_headers(response, total=len(projects), limit=limit, offset=offset)
    return [_with_file_urls(project) for project in projects[offset : offset + limit]]


@app.get("/projects/{project_id}")
def get_project(project_id: str, request: Request) -> dict:
    return _with_file_urls(_get_project_or_404(project_id, request))


@app.patch("/projects/{project_id}")
def update_project(project_id: str, payload: ProjectUpdate, request: Request) -> dict:
    project = _get_project_or_404(project_id, request)
    updated = store.update_project(project_id, payload)
    _audit(
        request,
        "project.update",
        actor_id=project.owner_id,
        resource_type="project",
        resource_id=project_id,
        metadata={"fields": sorted(payload.model_dump(exclude_unset=True).keys())},
    )
    return _with_file_urls(updated)


@app.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str, request: Request) -> Response:
    project = _get_project_or_404(project_id, request)
    store.delete_project(project_id)
    _audit(request, "project.delete", actor_id=project.owner_id, resource_type="project", resource_id=project_id)
    return Response(status_code=204)


@app.post("/projects/{project_id}/duplicate")
def duplicate_project(project_id: str, request: Request, response: Response) -> dict:
    project = _get_project_or_404(project_id, request)
    user = _current_user(request)
    key = _idempotency_key(request)
    if key:
        scope = f"projects:duplicate:{project_id}:{project.owner_id or 'public'}"
        request_hash = idempotency_store.request_hash({"project_id": project_id, "reset_outputs": True})
        record = _idempotency_record(key, scope, request_hash)
        replay = _replay_project_record(record, key=key, scope=scope, request=request, response=response)
        if replay is not None:
            return replay
    _enforce_project_quota(user)
    duplicate = store.duplicate_project(project_id)
    if key:
        idempotency_store.save(
            key=key,
            scope=scope,
            request_hash=request_hash,
            resource_type="project",
            resource_id=duplicate.id,
        )
        response.headers["x-idempotent-replay"] = "false"
    _audit(
        request,
        "project.duplicate",
        actor_id=project.owner_id,
        resource_type="project",
        resource_id=duplicate.id,
        metadata={"source_project_id": project_id},
    )
    usage_service.record(
        "project.duplicate",
        actor_id=_actor_id(user),
        resource_type="project",
        resource_id=duplicate.id,
        units=1,
        estimated_cost_cents=0,
        metadata={"source_project_id": project_id},
    )
    return _with_file_urls(duplicate)


@app.post("/projects/{project_id}/generate-script")
def generate_script(project_id: str, request: Request) -> dict:
    _get_project_or_404(project_id, request)
    return _sync_pipeline_response(pipeline.generate_script(project_id))


@app.post("/projects/{project_id}/collect-sources")
def collect_sources(project_id: str, request: Request) -> dict:
    _get_project_or_404(project_id, request)
    return _sync_pipeline_response(pipeline.collect_sources(project_id))


@app.post("/projects/{project_id}/generate-slides")
def generate_slides(project_id: str, request: Request) -> dict:
    _get_project_or_404(project_id, request)
    return _sync_pipeline_response(pipeline.generate_slides(project_id))


@app.post("/projects/{project_id}/generate-voice")
def generate_voice(project_id: str, request: Request) -> dict:
    _get_project_or_404(project_id, request)
    return _sync_pipeline_response(pipeline.generate_voice(project_id))


@app.post("/projects/{project_id}/prepare-avatar")
def prepare_avatar(project_id: str, request: Request) -> dict:
    _get_project_or_404(project_id, request)
    return _sync_pipeline_response(pipeline.prepare_avatar(project_id))


@app.post("/projects/{project_id}/render")
def render(project_id: str, request: Request) -> dict:
    _get_project_or_404(project_id, request)
    return _sync_pipeline_response(pipeline.render(project_id))


@app.post("/projects/{project_id}/generate-all")
def generate_all(project_id: str, request: Request) -> dict:
    _get_project_or_404(project_id, request)
    return _sync_pipeline_response(pipeline.generate_all(project_id))


@app.post("/projects/{project_id}/jobs/{job_type}")
def start_project_job(project_id: str, job_type: JobType, request: Request, response: Response) -> dict:
    return _start_project_job(project_id, job_type, request, response)


@app.post("/projects/{project_id}/generate-all-queued")
def generate_all_queued(project_id: str, request: Request, response: Response) -> dict:
    return _start_project_job(project_id, JobType.generate_all, request, response)


@app.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> dict:
    return _job_or_404(job_id, request)


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request) -> dict:
    visible_job = _get_job_or_404(job_id, request)
    try:
        job = job_runner.cancel(job_id)
        _audit(
            request,
            "job.cancel",
            actor_id=visible_job.owner_id,
            resource_type="job",
            resource_id=job.id,
            metadata={"project_id": job.project_id},
        )
        return job.model_dump(mode="json")
    except (InvalidIdentifierError, UnsafePathError):
        raise HTTPException(status_code=404, detail="Job not found") from None
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail="Job not found") from None
    except JobNotCancellableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, request: Request) -> dict:
    visible_job = _get_job_or_404(job_id, request)
    try:
        job = job_runner.retry(job_id)
        _audit(
            request,
            "job.retry",
            actor_id=visible_job.owner_id,
            resource_type="job",
            resource_id=job.id,
            metadata={"original_job_id": job_id, "project_id": job.project_id},
        )
        return job.model_dump(mode="json")
    except (InvalidIdentifierError, UnsafePathError):
        raise HTTPException(status_code=404, detail="Job not found") from None
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail="Job not found") from None
    except JobNotRetryableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.get("/jobs/{job_id}/events")
def get_job_events(
    job_id: str,
    request: Request,
    response: Response,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    events = _job_or_404(job_id, request).get("events", [])
    _set_pagination_headers(response, total=len(events), limit=limit, offset=offset)
    return events[offset : offset + limit]


@app.get("/projects/{project_id}/jobs")
def list_project_jobs(
    project_id: str,
    request: Request,
    response: Response,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    _get_project_or_404(project_id, request)
    jobs = job_store.list_for_project(project_id)
    _set_pagination_headers(response, total=len(jobs), limit=limit, offset=offset)
    return [job.model_dump(mode="json") for job in jobs[offset : offset + limit]]


@app.patch("/projects/{project_id}/scenes/{scene_id}")
def patch_scene(project_id: str, scene_id: str, payload: ScenePatch, request: Request) -> dict:
    project = _get_project_or_404(project_id, request)
    try:
        updated = store.patch_scene(project_id, scene_id, payload)
        _audit(
            request,
            "scene.update",
            actor_id=project.owner_id,
            resource_type="scene",
            resource_id=scene_id,
            metadata={"project_id": project_id, "fields": sorted(payload.model_dump(exclude_unset=True).keys())},
        )
        return _with_file_urls(updated)
    except SceneNotFoundError:
        raise HTTPException(status_code=404, detail="Scene not found") from None


@app.post("/projects/{project_id}/scenes")
def insert_scene(project_id: str, payload: SceneCreate, request: Request) -> dict:
    project = _get_project_or_404(project_id, request)
    try:
        existing_scene_ids = {scene.id for scene in project.scenes}
        updated = store.insert_scene(project_id, payload)
        inserted = next((scene for scene in updated.scenes if scene.id not in existing_scene_ids), updated.scenes[-1])
        _audit(
            request,
            "scene.create",
            actor_id=project.owner_id,
            resource_type="scene",
            resource_id=inserted.id,
            metadata={"project_id": project_id},
        )
        return _with_file_urls(updated)
    except SceneNotFoundError:
        raise HTTPException(status_code=404, detail="Scene not found") from None


@app.delete("/projects/{project_id}/scenes/{scene_id}")
def delete_scene(project_id: str, scene_id: str, request: Request) -> dict:
    project = _get_project_or_404(project_id, request)
    try:
        updated = store.delete_scene(project_id, scene_id)
        _audit(
            request,
            "scene.delete",
            actor_id=project.owner_id,
            resource_type="scene",
            resource_id=scene_id,
            metadata={"project_id": project_id},
        )
        return _with_file_urls(updated)
    except SceneNotFoundError:
        raise HTTPException(status_code=404, detail="Scene not found") from None


@app.post("/projects/{project_id}/scenes/reorder")
def reorder_scenes(project_id: str, payload: SceneReorder, request: Request) -> dict:
    project = _get_project_or_404(project_id, request)
    try:
        updated = store.reorder_scenes(project_id, payload)
        _audit(
            request,
            "scene.reorder",
            actor_id=project.owner_id,
            resource_type="project",
            resource_id=project_id,
            metadata={"scene_count": len(payload.scene_ids)},
        )
        return _with_file_urls(updated)
    except InvalidSceneOrderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.post("/projects/{project_id}/scenes/{scene_id}/regenerate-slide")
def regenerate_scene_slide(project_id: str, scene_id: str, request: Request) -> dict:
    _get_project_or_404(project_id, request)
    try:
        return _sync_pipeline_response(pipeline.regenerate_scene_slide(project_id, scene_id))
    except SceneNotFoundError:
        raise HTTPException(status_code=404, detail="Scene not found") from None


@app.get("/files/{file_path:path}")
def get_file(file_path: str, request: Request) -> FileResponse:
    try:
        path = ensure_within_directory(settings.data_dir, settings.data_dir / file_path)
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="File not found") from None
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if _auth_enabled():
        relative = path.relative_to(settings.data_dir)
        project_id = relative.parts[0] if relative.parts else ""
        _get_project_or_404(project_id, request)
    return FileResponse(path)


@app.get("/projects/{project_id}/status")
def project_status(project_id: str, request: Request) -> dict:
    project = _get_project_or_404(project_id, request)
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


@app.get("/projects/{project_id}/manifest")
def project_manifest(project_id: str, request: Request) -> dict:
    return _project_manifest(_get_project_or_404(project_id, request))


@app.get("/projects/{project_id}/result")
def project_result(project_id: str, request: Request) -> dict:
    project = _get_project_or_404(project_id, request)
    return _with_file_urls(project)["result"]
