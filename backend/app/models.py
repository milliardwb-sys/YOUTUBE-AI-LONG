from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from app.utils.security import UnsafeUrlError, validate_organization_id, validate_source_url, validate_user_id


class ProjectStatus(str, Enum):
    draft = "draft"
    queued = "queued"
    researching = "researching"
    sources_ready = "sources_ready"
    script_ready = "script_ready"
    visuals_ready = "visuals_ready"
    voice_ready = "voice_ready"
    rendering = "rendering"
    completed = "completed"
    cancelled = "cancelled"
    failed = "failed"


class VideoStyle(str, Enum):
    expert_review = "expert_review"
    tutorial = "tutorial"
    top_list = "top_list"
    trend_analysis = "trend_analysis"
    sales_video = "sales_video"


class VisualMode(str, Enum):
    ai_slides_only = "ai_slides_only"
    official_sites_plus_ai = "official_sites_plus_ai"


class SourceKind(str, Enum):
    official_website = "official_website"
    official_docs = "official_docs"
    press_kit = "press_kit"
    user_provided = "user_provided"
    ai_generated_fallback = "ai_generated_fallback"


class ScriptProviderName(str, Enum):
    template = "template"
    openai = "openai"


class VoiceProviderName(str, Enum):
    placeholder = "placeholder"
    openai = "openai"


class BrandTheme(str, Enum):
    dark = "dark"
    light = "light"
    neon = "neon"


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    cancelled = "cancelled"
    failed = "failed"


class JobType(str, Enum):
    generate_script = "generate_script"
    collect_sources = "collect_sources"
    generate_slides = "generate_slides"
    generate_voice = "generate_voice"
    prepare_avatar = "prepare_avatar"
    render = "render"
    generate_all = "generate_all"


class OrganizationRole(str, Enum):
    owner = "owner"
    admin = "admin"
    editor = "editor"
    viewer = "viewer"


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=256)
    name: str | None = Field(default=None, max_length=120)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        clean = value.strip().lower()
        if "@" not in clean or clean.startswith("@") or clean.endswith("@"):
            raise ValueError("email must be a valid email address")
        return clean

    @field_validator("name")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value else None


class UserLogin(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class UserPublic(BaseModel):
    id: str
    email: str
    name: str | None = None
    created_at: datetime


class AuthToken(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: UserPublic


class PlatformUser(BaseModel):
    id: str = Field(default_factory=lambda: f"user_{uuid4().hex[:12]}")
    email: str
    name: str | None = None
    password_hash: str
    disabled: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def public(self) -> UserPublic:
        return UserPublic(id=self.id, email=self.email, name=self.name, created_at=self.created_at)


class UserSession(BaseModel):
    id: str = Field(default_factory=lambda: f"session_{uuid4().hex[:12]}")
    user_id: str
    token_hash: str
    expires_at: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()


class OrganizationMemberCreate(BaseModel):
    email: str | None = Field(default=None, min_length=3, max_length=254)
    user_id: str | None = None
    role: OrganizationRole = OrganizationRole.editor

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip().lower()
        if "@" not in clean or clean.startswith("@") or clean.endswith("@"):
            raise ValueError("email must be a valid email address")
        return clean

    @field_validator("user_id")
    @classmethod
    def normalize_user_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_user_id(value.strip())

    @model_validator(mode="after")
    def require_target_user(self) -> "OrganizationMemberCreate":
        if not self.email and not self.user_id:
            raise ValueError("email or user_id is required")
        return self


class OrganizationMemberUpdate(BaseModel):
    role: OrganizationRole


class Organization(BaseModel):
    id: str = Field(default_factory=lambda: f"org_{uuid4().hex[:12]}")
    name: str
    created_by_user_id: str
    disabled: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)


class OrganizationMember(BaseModel):
    organization_id: str
    user_id: str
    email: str | None = None
    role: OrganizationRole
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("organization_id")
    @classmethod
    def normalize_organization_id(cls, value: str) -> str:
        return validate_organization_id(value.strip())

    @field_validator("user_id")
    @classmethod
    def validate_member_user_id(cls, value: str) -> str:
        return validate_user_id(value.strip())

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)


class SourceCandidate(BaseModel):
    id: str = Field(default_factory=lambda: f"source_{uuid4().hex[:8]}")
    name: str
    url: str
    kind: SourceKind = SourceKind.official_website
    license_note: str = "Official/public product page; verify brand and website terms before publication."
    reason: str = "Relevant source for the selected topic."
    screenshot_path: str | None = None
    status: Literal["planned", "captured", "fallback_card", "failed"] = "planned"
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("name", "url", "license_note", "reason")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class ProjectCreate(BaseModel):
    topic: str = Field(min_length=5, max_length=240)
    organization_id: str | None = None
    duration_minutes: int = Field(default=3, ge=1, le=10)
    style: VideoStyle = VideoStyle.expert_review
    language: Literal["ru", "en"] = "ru"
    audience: str = Field(default="широкая аудитория", max_length=180)
    visual_mode: VisualMode = VisualMode.ai_slides_only
    source_urls: list[str] = Field(default_factory=list, max_length=12)
    avatar_enabled: bool = False
    avatar_position: Literal[
        "bottom_right", "bottom_left", "top_right", "top_left"
    ] = "bottom_right"
    script_provider: ScriptProviderName = ScriptProviderName.template
    voice_provider: VoiceProviderName = VoiceProviderName.placeholder
    voice_id: str | None = Field(default=None, max_length=120)
    brand_theme: BrandTheme = BrandTheme.dark
    burn_subtitles: bool = False

    @field_validator("topic", "audience")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("organization_id")
    @classmethod
    def normalize_organization_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_organization_id(value.strip())

    @field_validator("source_urls")
    @classmethod
    def normalize_urls(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for url in value:
            clean = url.strip()
            if not clean:
                continue
            if not clean.startswith(("http://", "https://")):
                clean = "https://" + clean
            try:
                validate_source_url(clean)
            except UnsafeUrlError as exc:
                raise ValueError(str(exc)) from exc
            if clean not in seen:
                normalized.append(clean)
                seen.add(clean)
        return normalized


class ProjectUpdate(BaseModel):
    topic: str | None = Field(default=None, min_length=5, max_length=240)
    duration_minutes: int | None = Field(default=None, ge=1, le=10)
    style: VideoStyle | None = None
    language: Literal["ru", "en"] | None = None
    audience: str | None = Field(default=None, max_length=180)
    visual_mode: VisualMode | None = None
    source_urls: list[str] | None = Field(default=None, max_length=12)
    avatar_enabled: bool | None = None
    avatar_position: Literal[
        "bottom_right", "bottom_left", "top_right", "top_left"
    ] | None = None
    script_provider: ScriptProviderName | None = None
    voice_provider: VoiceProviderName | None = None
    voice_id: str | None = Field(default=None, max_length=120)
    brand_theme: BrandTheme | None = None
    burn_subtitles: bool | None = None

    @field_validator("source_urls")
    @classmethod
    def normalize_urls(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return ProjectCreate.normalize_urls(value)


class ScenePatch(BaseModel):
    title: str | None = Field(default=None, max_length=140)
    goal: str | None = Field(default=None, max_length=260)
    narration: str | None = Field(default=None, max_length=2600)
    on_screen_text: str | None = Field(default=None, max_length=220)
    visual_type: Literal["ai_slide", "screenshot", "table", "diagram"] | None = None
    duration_sec: int | None = Field(default=None, ge=5, le=240)
    avatar_visible: bool | None = None
    source_id: str | None = None
    visual_prompt: str | None = Field(default=None, max_length=700)
    notes: str | None = Field(default=None, max_length=700)


class SceneCreate(BaseModel):
    title: str = Field(max_length=140)
    goal: str = Field(default="добавить поясняющую сцену", max_length=260)
    narration: str = Field(default="Новая сцена. Добавьте текст озвучки перед финальным рендером.", max_length=2600)
    on_screen_text: str | None = Field(default=None, max_length=220)
    visual_type: Literal["ai_slide", "screenshot", "table", "diagram"] = "ai_slide"
    duration_sec: int = Field(default=12, ge=5, le=240)
    avatar_visible: bool = True
    source_id: str | None = None
    visual_prompt: str | None = Field(default=None, max_length=700)
    notes: str | None = Field(default="Manual scene inserted from API.", max_length=700)
    after_scene_id: str | None = None
    order: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def fill_screen_text(self) -> "SceneCreate":
        if self.on_screen_text is None:
            self.on_screen_text = self.title
        return self


class SceneReorder(BaseModel):
    scene_ids: list[str] = Field(min_length=1)

    @field_validator("scene_ids")
    @classmethod
    def unique_scene_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("scene_ids must be unique")
        return value


class Scene(BaseModel):
    id: str = Field(default_factory=lambda: f"scene_{uuid4().hex[:8]}")
    order: int
    title: str
    goal: str
    narration: str
    on_screen_text: str
    visual_type: Literal["ai_slide", "screenshot", "table", "diagram"] = "ai_slide"
    visual_prompt: str | None = None
    notes: str | None = None
    duration_sec: int
    start_sec: int = 0
    avatar_visible: bool = True
    source_id: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    visual_path: str | None = None
    audio_path: str | None = None


class ProjectResult(BaseModel):
    final_video_path: str | None = None
    subtitles_path: str | None = None
    captions_vtt_path: str | None = None
    description_path: str | None = None
    sources_path: str | None = None
    storyboard_path: str | None = None
    thumbnail_prompt_path: str | None = None
    thumbnail_path: str | None = None
    title_options_path: str | None = None
    youtube_metadata_path: str | None = None
    quality_report_path: str | None = None
    voice_manifest_path: str | None = None
    render_manifest_path: str | None = None
    export_package_path: str | None = None
    warnings: list[str] = Field(default_factory=list)


class Project(BaseModel):
    id: str = Field(default_factory=lambda: f"project_{uuid4().hex[:12]}")
    owner_id: str | None = None
    organization_id: str | None = None
    topic: str
    duration_minutes: int
    style: VideoStyle
    language: Literal["ru", "en"]
    audience: str
    visual_mode: VisualMode
    source_urls: list[str] = Field(default_factory=list)
    sources: list[SourceCandidate] = Field(default_factory=list)
    avatar_enabled: bool = False
    avatar_position: Literal[
        "bottom_right", "bottom_left", "top_right", "top_left"
    ] = "bottom_right"
    script_provider: ScriptProviderName = ScriptProviderName.template
    voice_provider: VoiceProviderName = VoiceProviderName.placeholder
    voice_id: str | None = None
    brand_theme: BrandTheme = BrandTheme.dark
    burn_subtitles: bool = False
    status: ProjectStatus = ProjectStatus.draft
    current_step: str = "created"
    scenes: list[Scene] = Field(default_factory=list)
    result: ProjectResult = Field(default_factory=ProjectResult)
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self, step: str | None = None) -> None:
        self.updated_at = datetime.now(timezone.utc)
        if step:
            self.current_step = step


class ProjectJob(BaseModel):
    id: str = Field(default_factory=lambda: f"job_{uuid4().hex[:12]}")
    project_id: str
    owner_id: str | None = None
    organization_id: str | None = None
    type: JobType
    status: JobStatus = JobStatus.queued
    progress: int = Field(default=0, ge=0, le=100)
    current_step: str = "queued"
    error: str | None = None
    events: list[dict[str, str | int | None]] = Field(default_factory=list)
    result_project_status: ProjectStatus | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def touch(self, step: str | None = None) -> None:
        self.updated_at = datetime.now(timezone.utc)
        if step:
            self.current_step = step

    def add_event(self, event: str, message: str | None = None, progress: int | None = None) -> None:
        self.events.append(
            {
                "event": event,
                "message": message,
                "progress": self.progress if progress is None else progress,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def mark_running(self, step: str = "running") -> None:
        self.status = JobStatus.running
        self.started_at = self.started_at or datetime.now(timezone.utc)
        self.touch(step)
        self.add_event("running", step)

    def mark_completed(self, project_status: ProjectStatus | str | None = None) -> None:
        self.status = JobStatus.completed
        self.progress = 100
        self.completed_at = datetime.now(timezone.utc)
        if project_status is not None:
            self.result_project_status = ProjectStatus(project_status)
        self.touch("completed")
        self.add_event("completed", str(project_status) if project_status else None, 100)

    def mark_failed(self, error: str) -> None:
        self.status = JobStatus.failed
        self.error = error
        self.completed_at = datetime.now(timezone.utc)
        self.touch("failed")
        self.add_event("failed", error)

    def mark_cancelled(self, reason: str = "Job cancelled") -> None:
        self.status = JobStatus.cancelled
        self.error = reason
        self.completed_at = datetime.now(timezone.utc)
        self.touch("cancelled")
        self.add_event("cancelled", reason)
