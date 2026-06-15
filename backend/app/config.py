from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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
    cors_origins: list[str]
    allow_unsafe_http_sources: bool
    allow_private_source_urls: bool
    cleanup_retention_days: int


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

    return Settings(
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
        cors_origins=_env_list("CORS_ORIGINS", ["http://localhost:19006", "http://localhost:8081"]),
        allow_unsafe_http_sources=_env_bool("ALLOW_UNSAFE_HTTP_SOURCES", False),
        allow_private_source_urls=_env_bool("ALLOW_PRIVATE_SOURCE_URLS", False),
        cleanup_retention_days=_env_int("CLEANUP_RETENTION_DAYS", 14),
    )
