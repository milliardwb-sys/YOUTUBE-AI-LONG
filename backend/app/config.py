from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

LOCAL_ENVS = {"local", "test", "dev", "development"}
WEAK_PRODUCTION_API_KEYS = {
    "CHANGE_ME",
    "CHANGE_ME_TO_A_LONG_RANDOM_SECRET",
    "changeme",
    "secret",
    "password",
    "test",
}
MIN_PRODUCTION_API_KEY_LENGTH = 32


@dataclass(frozen=True)
class Settings:
    app_env: str
    data_dir: Path
    public_base_url: str
    log_level: str
    json_logs: bool
    ffmpeg_bin: str
    render_width: int
    render_height: int
    render_fps: int
    project_storage_backend: str
    database_url: str | None
    database_connect_timeout_seconds: int
    database_auto_migrate: bool
    enable_browser_screenshots: bool
    browser_timeout_ms: int
    default_script_provider: str
    default_voice_provider: str
    openai_api_key: str | None
    openai_model: str
    openai_temperature: float
    openai_tts_model: str
    openai_tts_voice: str
    max_openai_tts_chars: int
    enable_model_images: bool
    openai_image_model: str
    openai_image_size: str
    heygen_api_key: str | None
    heygen_api_base_url: str
    heygen_avatar_id: str | None
    heygen_voice_id: str | None
    heygen_resolution: str
    heygen_output_format: str
    heygen_remove_background: bool
    heygen_enable_motion_prompt: bool
    heygen_poll_seconds: int
    heygen_webhook_secret: str | None
    heygen_webhook_tolerance_seconds: int
    avatar_auto_sync_enabled: bool
    avatar_auto_sync_interval_seconds: int
    avatar_auto_render_after_sync: bool
    burn_subtitles_by_default: bool
    run_jobs_inline: bool
    execute_jobs_in_api: bool
    job_workers: int
    job_storage_backend: str
    api_key: str | None
    admin_api_key: str | None
    enable_user_auth: bool
    access_token_ttl_minutes: int
    oidc_enabled: bool
    oidc_issuer_url: str | None
    oidc_audience: str | None
    oidc_jwks_url: str | None
    oidc_algorithms: list[str]
    oidc_email_claim: str
    oidc_name_claim: str
    audit_storage_backend: str
    support_storage_backend: str
    idempotency_storage_backend: str
    usage_storage_backend: str
    rate_limit_requests_per_minute: int
    cors_origins: list[str]
    allow_unsafe_http_sources: bool
    allow_private_source_urls: bool
    search_provider: str
    brave_search_api_key: str | None
    brave_search_endpoint: str
    search_result_count: int
    artifact_storage_backend: str
    artifact_url_ttl_seconds: int
    s3_bucket: str | None
    s3_region: str | None
    s3_endpoint_url: str | None
    s3_access_key_id: str | None
    s3_secret_access_key: str | None
    s3_prefix: str
    s3_public_base_url: str | None
    cleanup_retention_days: int
    render_timeout_seconds: int
    max_request_body_bytes: int
    usage_max_projects_per_user: int
    usage_max_active_jobs_per_user: int
    usage_llm_job_cost_cents: int
    usage_tts_cost_cents_per_minute: int
    usage_render_cost_cents_per_minute: int
    stripe_api_key: str | None
    stripe_api_version: str
    stripe_webhook_secret: str | None
    stripe_pro_price_id: str | None
    stripe_success_url: str
    stripe_cancel_url: str
    stripe_portal_return_url: str
    billing_pro_max_projects: int
    billing_pro_max_active_jobs: int


class ConfigurationError(RuntimeError):
    pass


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_optional(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_list(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if value is None:
        return default
    items = [item.strip() for item in value.split(",")]
    return [item for item in items if item]


def get_settings() -> Settings:
    data_dir = Path(os.getenv("DATA_DIR", "./data/projects")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        app_env=os.getenv("APP_ENV", "local"),
        data_dir=data_dir,
        public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8000"),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        json_logs=_env_bool("JSON_LOGS", False),
        ffmpeg_bin=os.getenv("FFMPEG_BIN", "ffmpeg"),
        render_width=_env_int("DEFAULT_RENDER_WIDTH", 1920),
        render_height=_env_int("DEFAULT_RENDER_HEIGHT", 1080),
        render_fps=_env_int("DEFAULT_RENDER_FPS", 30),
        project_storage_backend=os.getenv("PROJECT_STORAGE_BACKEND", "local").strip().lower(),
        database_url=_env_optional("DATABASE_URL"),
        database_connect_timeout_seconds=max(1, _env_int("DATABASE_CONNECT_TIMEOUT_SECONDS", 10)),
        database_auto_migrate=_env_bool("DATABASE_AUTO_MIGRATE", True),
        enable_browser_screenshots=_env_bool("ENABLE_BROWSER_SCREENSHOTS", False),
        browser_timeout_ms=_env_int("BROWSER_SCREENSHOT_TIMEOUT_MS", 12000),
        default_script_provider=os.getenv("DEFAULT_SCRIPT_PROVIDER", "template").strip().lower(),
        default_voice_provider=os.getenv("DEFAULT_VOICE_PROVIDER", "placeholder").strip().lower(),
        openai_api_key=_env_optional("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        openai_temperature=_env_float("OPENAI_TEMPERATURE", 0.55),
        openai_tts_model=os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
        openai_tts_voice=os.getenv("OPENAI_TTS_VOICE", "alloy"),
        max_openai_tts_chars=_env_int("MAX_OPENAI_TTS_CHARS", 3800),
        enable_model_images=_env_bool("ENABLE_MODEL_IMAGES", False),
        openai_image_model=os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1").strip(),
        openai_image_size=os.getenv("OPENAI_IMAGE_SIZE", "1536x1024").strip(),
        heygen_api_key=_env_optional("HEYGEN_API_KEY"),
        heygen_api_base_url=os.getenv("HEYGEN_API_BASE_URL", "https://api.heygen.com").strip().rstrip("/"),
        heygen_avatar_id=_env_optional("HEYGEN_AVATAR_ID"),
        heygen_voice_id=_env_optional("HEYGEN_VOICE_ID"),
        heygen_resolution=os.getenv("HEYGEN_RESOLUTION", "1080p").strip(),
        heygen_output_format=os.getenv("HEYGEN_OUTPUT_FORMAT", "mp4").strip().lower(),
        heygen_remove_background=_env_bool("HEYGEN_REMOVE_BACKGROUND", True),
        heygen_enable_motion_prompt=_env_bool("HEYGEN_ENABLE_MOTION_PROMPT", False),
        heygen_poll_seconds=max(0, _env_int("HEYGEN_POLL_SECONDS", 0)),
        heygen_webhook_secret=_env_optional("HEYGEN_WEBHOOK_SECRET"),
        heygen_webhook_tolerance_seconds=max(30, _env_int("HEYGEN_WEBHOOK_TOLERANCE_SECONDS", 300)),
        avatar_auto_sync_enabled=_env_bool("AVATAR_AUTO_SYNC_ENABLED", False),
        avatar_auto_sync_interval_seconds=max(15, _env_int("AVATAR_AUTO_SYNC_INTERVAL_SECONDS", 60)),
        avatar_auto_render_after_sync=_env_bool("AVATAR_AUTO_RENDER_AFTER_SYNC", True),
        burn_subtitles_by_default=_env_bool("BURN_SUBTITLES_BY_DEFAULT", False),
        run_jobs_inline=_env_bool("RUN_JOBS_INLINE", False),
        execute_jobs_in_api=_env_bool("EXECUTE_JOBS_IN_API", True),
        job_workers=_env_int("JOB_WORKERS", 2),
        job_storage_backend=os.getenv("JOB_STORAGE_BACKEND", "local").strip().lower(),
        api_key=_env_optional("API_KEY"),
        admin_api_key=_env_optional("ADMIN_API_KEY"),
        enable_user_auth=_env_bool("ENABLE_USER_AUTH", False),
        access_token_ttl_minutes=max(5, _env_int("ACCESS_TOKEN_TTL_MINUTES", 1440)),
        oidc_enabled=_env_bool("OIDC_ENABLED", False),
        oidc_issuer_url=_env_optional("OIDC_ISSUER_URL"),
        oidc_audience=_env_optional("OIDC_AUDIENCE"),
        oidc_jwks_url=_env_optional("OIDC_JWKS_URL"),
        oidc_algorithms=_env_list("OIDC_ALGORITHMS", ["RS256"]),
        oidc_email_claim=os.getenv("OIDC_EMAIL_CLAIM", "email").strip() or "email",
        oidc_name_claim=os.getenv("OIDC_NAME_CLAIM", "name").strip() or "name",
        audit_storage_backend=os.getenv("AUDIT_STORAGE_BACKEND", "local").strip().lower(),
        support_storage_backend=os.getenv("SUPPORT_STORAGE_BACKEND", "local").strip().lower(),
        idempotency_storage_backend=os.getenv("IDEMPOTENCY_STORAGE_BACKEND", "local").strip().lower(),
        usage_storage_backend=os.getenv("USAGE_STORAGE_BACKEND", "local").strip().lower(),
        rate_limit_requests_per_minute=_env_int("RATE_LIMIT_REQUESTS_PER_MINUTE", 0),
        cors_origins=_env_list("CORS_ORIGINS", ["http://localhost:19006", "http://localhost:8081"]),
        allow_unsafe_http_sources=_env_bool("ALLOW_UNSAFE_HTTP_SOURCES", False),
        allow_private_source_urls=_env_bool("ALLOW_PRIVATE_SOURCE_URLS", False),
        search_provider=os.getenv("SEARCH_PROVIDER", "disabled").strip().lower(),
        brave_search_api_key=_env_optional("BRAVE_SEARCH_API_KEY"),
        brave_search_endpoint=os.getenv(
            "BRAVE_SEARCH_ENDPOINT",
            "https://api.search.brave.com/res/v1/web/search",
        ).strip(),
        search_result_count=max(0, min(10, _env_int("SEARCH_RESULT_COUNT", 3))),
        artifact_storage_backend=os.getenv("ARTIFACT_STORAGE_BACKEND", "local").strip().lower(),
        artifact_url_ttl_seconds=max(60, _env_int("ARTIFACT_URL_TTL_SECONDS", 3600)),
        s3_bucket=_env_optional("S3_BUCKET"),
        s3_region=_env_optional("S3_REGION"),
        s3_endpoint_url=_env_optional("S3_ENDPOINT_URL"),
        s3_access_key_id=_env_optional("S3_ACCESS_KEY_ID"),
        s3_secret_access_key=_env_optional("S3_SECRET_ACCESS_KEY"),
        s3_prefix=os.getenv("S3_PREFIX", "ai-video-studio").strip().strip("/"),
        s3_public_base_url=_env_optional("S3_PUBLIC_BASE_URL"),
        cleanup_retention_days=_env_int("CLEANUP_RETENTION_DAYS", 14),
        render_timeout_seconds=max(1, _env_int("RENDER_TIMEOUT_SECONDS", 1800)),
        max_request_body_bytes=max(0, _env_int("MAX_REQUEST_BODY_BYTES", 2_000_000)),
        usage_max_projects_per_user=max(0, _env_int("USAGE_MAX_PROJECTS_PER_USER", 25)),
        usage_max_active_jobs_per_user=max(0, _env_int("USAGE_MAX_ACTIVE_JOBS_PER_USER", 2)),
        usage_llm_job_cost_cents=max(0, _env_int("USAGE_LLM_JOB_COST_CENTS", 1)),
        usage_tts_cost_cents_per_minute=max(0, _env_int("USAGE_TTS_COST_CENTS_PER_MINUTE", 1)),
        usage_render_cost_cents_per_minute=max(0, _env_int("USAGE_RENDER_COST_CENTS_PER_MINUTE", 2)),
        stripe_api_key=_env_optional("STRIPE_API_KEY"),
        stripe_api_version=os.getenv("STRIPE_API_VERSION", "2026-02-25.clover").strip(),
        stripe_webhook_secret=_env_optional("STRIPE_WEBHOOK_SECRET"),
        stripe_pro_price_id=_env_optional("STRIPE_PRO_PRICE_ID"),
        stripe_success_url=os.getenv("STRIPE_SUCCESS_URL", "http://localhost:19006/billing/success").strip(),
        stripe_cancel_url=os.getenv("STRIPE_CANCEL_URL", "http://localhost:19006/billing/cancel").strip(),
        stripe_portal_return_url=os.getenv("STRIPE_PORTAL_RETURN_URL", "http://localhost:19006/billing").strip(),
        billing_pro_max_projects=max(0, _env_int("BILLING_PRO_MAX_PROJECTS", 250)),
        billing_pro_max_active_jobs=max(0, _env_int("BILLING_PRO_MAX_ACTIVE_JOBS", 10)),
    )
    validate_settings(settings)
    return settings


def validate_settings(settings: Settings) -> None:
    if settings.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigurationError("LOG_LEVEL must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL")
    if settings.project_storage_backend not in {"local", "postgres"}:
        raise ConfigurationError("PROJECT_STORAGE_BACKEND must be either 'local' or 'postgres'")
    if settings.project_storage_backend == "postgres" and not settings.database_url:
        raise ConfigurationError("DATABASE_URL is required when PROJECT_STORAGE_BACKEND=postgres")
    if settings.job_storage_backend not in {"local", "postgres"}:
        raise ConfigurationError("JOB_STORAGE_BACKEND must be either 'local' or 'postgres'")
    if settings.job_storage_backend == "postgres" and not settings.database_url:
        raise ConfigurationError("DATABASE_URL is required when JOB_STORAGE_BACKEND=postgres")
    if settings.artifact_storage_backend not in {"local", "s3"}:
        raise ConfigurationError("ARTIFACT_STORAGE_BACKEND must be either 'local' or 's3'")
    if settings.artifact_storage_backend == "s3" and not settings.s3_bucket:
        raise ConfigurationError("S3_BUCKET is required when ARTIFACT_STORAGE_BACKEND=s3")
    if bool(settings.s3_access_key_id) != bool(settings.s3_secret_access_key):
        raise ConfigurationError("S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY must be configured together")
    if settings.stripe_api_key and not settings.stripe_pro_price_id:
        raise ConfigurationError("STRIPE_PRO_PRICE_ID is required when STRIPE_API_KEY is configured")
    if settings.app_env not in LOCAL_ENVS and settings.stripe_api_key and not settings.stripe_webhook_secret:
        raise ConfigurationError("STRIPE_WEBHOOK_SECRET is required when Stripe billing is enabled in non-local environments")
    if settings.oidc_enabled:
        if not settings.enable_user_auth:
            raise ConfigurationError("ENABLE_USER_AUTH=true is required when OIDC_ENABLED=true")
        if not settings.oidc_issuer_url:
            raise ConfigurationError("OIDC_ISSUER_URL is required when OIDC_ENABLED=true")
        if not settings.oidc_audience:
            raise ConfigurationError("OIDC_AUDIENCE is required when OIDC_ENABLED=true")
        if not settings.oidc_jwks_url:
            raise ConfigurationError("OIDC_JWKS_URL is required when OIDC_ENABLED=true")
        if not settings.oidc_algorithms:
            raise ConfigurationError("OIDC_ALGORITHMS must contain at least one algorithm when OIDC_ENABLED=true")
    if settings.heygen_api_key and not settings.heygen_avatar_id:
        raise ConfigurationError("HEYGEN_AVATAR_ID is required when HEYGEN_API_KEY is configured")
    if settings.heygen_resolution not in {"720p", "1080p", "4k"}:
        raise ConfigurationError("HEYGEN_RESOLUTION must be one of 720p, 1080p, 4k")
    if settings.heygen_output_format not in {"mp4", "webm"}:
        raise ConfigurationError("HEYGEN_OUTPUT_FORMAT must be either mp4 or webm")
    if settings.enable_model_images and not settings.openai_api_key:
        raise ConfigurationError("OPENAI_API_KEY is required when ENABLE_MODEL_IMAGES=true")
    if settings.audit_storage_backend not in {"local", "postgres"}:
        raise ConfigurationError("AUDIT_STORAGE_BACKEND must be either 'local' or 'postgres'")
    if settings.audit_storage_backend == "postgres" and not settings.database_url:
        raise ConfigurationError("DATABASE_URL is required when AUDIT_STORAGE_BACKEND=postgres")
    if settings.support_storage_backend not in {"local", "postgres"}:
        raise ConfigurationError("SUPPORT_STORAGE_BACKEND must be either 'local' or 'postgres'")
    if settings.support_storage_backend == "postgres" and not settings.database_url:
        raise ConfigurationError("DATABASE_URL is required when SUPPORT_STORAGE_BACKEND=postgres")
    if settings.idempotency_storage_backend not in {"local", "postgres"}:
        raise ConfigurationError("IDEMPOTENCY_STORAGE_BACKEND must be either 'local' or 'postgres'")
    if settings.idempotency_storage_backend == "postgres" and not settings.database_url:
        raise ConfigurationError("DATABASE_URL is required when IDEMPOTENCY_STORAGE_BACKEND=postgres")
    if settings.usage_storage_backend not in {"local", "postgres"}:
        raise ConfigurationError("USAGE_STORAGE_BACKEND must be either 'local' or 'postgres'")
    if settings.usage_storage_backend == "postgres" and not settings.database_url:
        raise ConfigurationError("DATABASE_URL is required when USAGE_STORAGE_BACKEND=postgres")
    if settings.app_env in LOCAL_ENVS or not settings.api_key:
        return
    if settings.api_key in WEAK_PRODUCTION_API_KEYS:
        raise ConfigurationError("API_KEY uses a known placeholder value")
    if len(settings.api_key) < MIN_PRODUCTION_API_KEY_LENGTH:
        raise ConfigurationError(
            f"API_KEY must be at least {MIN_PRODUCTION_API_KEY_LENGTH} characters in non-local environments"
        )
