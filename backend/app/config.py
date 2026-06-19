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
    ffmpeg_bin: str
    render_width: int
    render_height: int
    render_fps: int
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
    burn_subtitles_by_default: bool
    run_jobs_inline: bool
    job_workers: int
    api_key: str | None
    enable_user_auth: bool
    access_token_ttl_minutes: int
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
    cleanup_retention_days: int
    render_timeout_seconds: int
    max_request_body_bytes: int
    usage_max_projects_per_user: int
    usage_max_active_jobs_per_user: int
    usage_llm_job_cost_cents: int
    usage_tts_cost_cents_per_minute: int
    usage_render_cost_cents_per_minute: int


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
        ffmpeg_bin=os.getenv("FFMPEG_BIN", "ffmpeg"),
        render_width=_env_int("DEFAULT_RENDER_WIDTH", 1920),
        render_height=_env_int("DEFAULT_RENDER_HEIGHT", 1080),
        render_fps=_env_int("DEFAULT_RENDER_FPS", 30),
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
        burn_subtitles_by_default=_env_bool("BURN_SUBTITLES_BY_DEFAULT", False),
        run_jobs_inline=_env_bool("RUN_JOBS_INLINE", False),
        job_workers=_env_int("JOB_WORKERS", 2),
        api_key=_env_optional("API_KEY"),
        enable_user_auth=_env_bool("ENABLE_USER_AUTH", False),
        access_token_ttl_minutes=max(5, _env_int("ACCESS_TOKEN_TTL_MINUTES", 1440)),
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
        cleanup_retention_days=_env_int("CLEANUP_RETENTION_DAYS", 14),
        render_timeout_seconds=max(1, _env_int("RENDER_TIMEOUT_SECONDS", 1800)),
        max_request_body_bytes=max(0, _env_int("MAX_REQUEST_BODY_BYTES", 2_000_000)),
        usage_max_projects_per_user=max(0, _env_int("USAGE_MAX_PROJECTS_PER_USER", 25)),
        usage_max_active_jobs_per_user=max(0, _env_int("USAGE_MAX_ACTIVE_JOBS_PER_USER", 2)),
        usage_llm_job_cost_cents=max(0, _env_int("USAGE_LLM_JOB_COST_CENTS", 1)),
        usage_tts_cost_cents_per_minute=max(0, _env_int("USAGE_TTS_COST_CENTS_PER_MINUTE", 1)),
        usage_render_cost_cents_per_minute=max(0, _env_int("USAGE_RENDER_COST_CENTS_PER_MINUTE", 2)),
    )
    validate_settings(settings)
    return settings


def validate_settings(settings: Settings) -> None:
    if settings.app_env in LOCAL_ENVS or not settings.api_key:
        return
    if settings.api_key in WEAK_PRODUCTION_API_KEYS:
        raise ConfigurationError("API_KEY uses a known placeholder value")
    if len(settings.api_key) < MIN_PRODUCTION_API_KEY_LENGTH:
        raise ConfigurationError(
            f"API_KEY must be at least {MIN_PRODUCTION_API_KEY_LENGTH} characters in non-local environments"
        )
