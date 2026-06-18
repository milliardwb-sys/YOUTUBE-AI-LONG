from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.models import (
    Project,
    ProjectCreate,
    ProjectResult,
    ProjectStatus,
    ProjectUpdate,
    Scene,
    SceneCreate,
    ScenePatch,
    SceneReorder,
    ScriptProviderName,
    VoiceProviderName,
)
from app.utils.files import ensure_dir, read_json, write_json
from app.utils.security import ensure_within_directory, validate_project_id, validate_scene_id


class ProjectNotFoundError(KeyError):
    pass


class SceneNotFoundError(KeyError):
    pass


class InvalidSceneOrderError(ValueError):
    pass


class ProjectStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        ensure_dir(settings.data_dir)

    def project_dir(self, project_id: str) -> Path:
        validate_project_id(project_id)
        return ensure_within_directory(self.settings.data_dir, self.settings.data_dir / project_id)

    def project_file(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "project.json"

    def create_project(
        self,
        payload: ProjectCreate,
        *,
        owner_id: str | None = None,
        organization_id: str | None = None,
    ) -> Project:
        data = payload.model_dump()
        payload_organization_id = data.pop("organization_id", None)
        if organization_id is None:
            organization_id = payload_organization_id
        explicit_fields = payload.model_fields_set

        if "script_provider" not in explicit_fields:
            try:
                data["script_provider"] = ScriptProviderName(self.settings.default_script_provider)
            except ValueError:
                data["script_provider"] = ScriptProviderName.template

        if "voice_provider" not in explicit_fields:
            try:
                data["voice_provider"] = VoiceProviderName(self.settings.default_voice_provider)
            except ValueError:
                data["voice_provider"] = VoiceProviderName.placeholder

        if "burn_subtitles" not in explicit_fields:
            data["burn_subtitles"] = self.settings.burn_subtitles_by_default

        project = Project(**data, owner_id=owner_id, organization_id=organization_id)
        ensure_dir(self.project_dir(project.id))
        self.save(project)
        return project

    def duplicate_project(
        self,
        project_id: str,
        *,
        reset_outputs: bool = True,
        owner_id: str | None = None,
        organization_id: str | None = None,
    ) -> Project:
        original = self.get(project_id)
        clone_data = original.model_dump(mode="json")
        clone_data["id"] = f"project_{uuid4().hex[:12]}"
        clone_data["topic"] = f"{original.topic} — копия"
        clone_data["status"] = ProjectStatus.draft
        clone_data["current_step"] = "duplicated"
        clone_data["error"] = None
        if owner_id is not None:
            clone_data["owner_id"] = owner_id
        if organization_id is not None:
            clone_data["organization_id"] = organization_id
        if reset_outputs:
            clone_data["sources"] = []
            clone_data["scenes"] = []
            clone_data["result"] = ProjectResult().model_dump(mode="json")
        project = Project.model_validate(clone_data)
        ensure_dir(self.project_dir(project.id))
        self.save(project)
        return project

    def update_project(self, project_id: str, payload: ProjectUpdate) -> Project:
        project = self.get(project_id)
        changes = payload.model_dump(exclude_unset=True)
        script_inputs = {
            "topic",
            "duration_minutes",
            "style",
            "language",
            "audience",
            "visual_mode",
            "source_urls",
            "script_provider",
        }
        render_inputs = {
            "avatar_enabled",
            "avatar_position",
            "voice_provider",
            "voice_id",
            "brand_theme",
            "burn_subtitles",
        }
        for key, value in changes.items():
            setattr(project, key, value)
        if script_inputs.intersection(changes):
            self._reset_generated_content(project)
        elif render_inputs.intersection(changes):
            self._clear_render_outputs(project)
        project.error = None
        project.touch("project_updated")
        self.save(project)
        return project

    def patch_scene(self, project_id: str, scene_id: str, payload: ScenePatch) -> Project:
        validate_scene_id(scene_id)
        project = self.get(project_id)
        scene = next((item for item in project.scenes if item.id == scene_id), None)
        if scene is None:
            raise SceneNotFoundError(scene_id)
        changes = payload.model_dump(exclude_unset=True)
        clear_visual = False
        clear_audio = False
        for key, value in changes.items():
            setattr(scene, key, value)
            if key in {"title", "goal", "on_screen_text", "visual_type", "source_id", "visual_prompt"}:
                clear_visual = True
            if key in {"narration", "duration_sec"}:
                clear_audio = True
        if clear_visual:
            scene.visual_path = None
            self._clear_render_outputs(project)
        if clear_audio:
            scene.audio_path = None
            project.result.subtitles_path = None
            project.result.captions_vtt_path = None
            project.result.voice_manifest_path = None
            self._clear_render_outputs(project)
        self._sync_scene_source(project, scene_id)
        self._recalculate_scene_timings(project)
        project.status = ProjectStatus.draft
        project.touch("scene_updated")
        self.save(project)
        return project

    def insert_scene(self, project_id: str, payload: SceneCreate) -> Project:
        project = self.get(project_id)
        if payload.after_scene_id:
            validate_scene_id(payload.after_scene_id)
        order = self._resolve_insert_order(project, payload)
        scene = Scene(
            order=order,
            title=payload.title,
            goal=payload.goal,
            narration=payload.narration,
            on_screen_text=payload.on_screen_text or payload.title,
            visual_type=payload.visual_type,
            visual_prompt=payload.visual_prompt,
            notes=payload.notes,
            duration_sec=payload.duration_sec,
            avatar_visible=payload.avatar_visible,
            source_id=payload.source_id,
        )
        for item in project.scenes:
            if item.order >= order:
                item.order += 1
        project.scenes.append(scene)
        project.scenes.sort(key=lambda item: item.order)
        self._sync_scene_source(project, scene.id)
        self._normalize_scene_order(project)
        self._clear_render_outputs(project)
        project.status = ProjectStatus.draft
        project.error = None
        project.touch("scene_inserted")
        self.save(project)
        return project

    def delete_scene(self, project_id: str, scene_id: str) -> Project:
        validate_scene_id(scene_id)
        project = self.get(project_id)
        before = len(project.scenes)
        project.scenes = [scene for scene in project.scenes if scene.id != scene_id]
        if len(project.scenes) == before:
            raise SceneNotFoundError(scene_id)
        self._normalize_scene_order(project)
        self._clear_render_outputs(project)
        project.status = ProjectStatus.draft
        project.error = None
        project.touch("scene_deleted")
        self.save(project)
        return project

    def reorder_scenes(self, project_id: str, payload: SceneReorder) -> Project:
        project = self.get(project_id)
        current_ids = {scene.id for scene in project.scenes}
        provided_ids = set(payload.scene_ids)
        if current_ids != provided_ids:
            missing = sorted(current_ids - provided_ids)
            unknown = sorted(provided_ids - current_ids)
            raise InvalidSceneOrderError(f"Scene ids mismatch. missing={missing}, unknown={unknown}")
        by_id = {scene.id: scene for scene in project.scenes}
        project.scenes = [by_id[scene_id] for scene_id in payload.scene_ids]
        self._normalize_scene_order(project)
        project.status = ProjectStatus.draft
        project.error = None
        project.touch("scenes_reordered")
        self.save(project)
        return project

    def delete_project(self, project_id: str) -> None:
        project_dir = self.project_dir(project_id)
        if not self.project_file(project_id).exists():
            raise ProjectNotFoundError(project_id)
        shutil.rmtree(project_dir, ignore_errors=True)

    def save(self, project: Project) -> None:
        project.touch()
        write_json(self.project_file(project.id), project.model_dump(mode="json"))

    def get(self, project_id: str) -> Project:
        path = self.project_file(project_id)
        if not path.exists():
            raise ProjectNotFoundError(project_id)
        return Project.model_validate(read_json(path))

    def list_projects(self, *, owner_id: str | None = None) -> list[Project]:
        projects: list[Project] = []
        for project_file in sorted(self.settings.data_dir.glob("project_*/project.json")):
            project = Project.model_validate(read_json(project_file))
            if owner_id is not None and project.owner_id != owner_id:
                continue
            projects.append(project)
        return sorted(projects, key=lambda item: (item.created_at, item.id), reverse=True)

    def cleanup_old_projects(self, retention_days: int | None = None) -> dict[str, int]:
        retention = retention_days if retention_days is not None else self.settings.cleanup_retention_days
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, retention))
        removed = 0
        skipped = 0
        for project in self.list_projects():
            if project.status in {ProjectStatus.queued, ProjectStatus.rendering}:
                skipped += 1
                continue
            if project.updated_at >= cutoff:
                skipped += 1
                continue
            self.delete_project(project.id)
            removed += 1
        return {"removed_projects": removed, "skipped_projects": skipped}

    def stats(self) -> dict:
        projects = self.list_projects()
        by_status: dict[str, int] = {}
        total_files = 0
        total_bytes = 0
        for project in projects:
            by_status[project.status.value] = by_status.get(project.status.value, 0) + 1
        if self.settings.data_dir.exists():
            for path in self.settings.data_dir.rglob("*"):
                if path.is_file():
                    total_files += 1
                    try:
                        total_bytes += path.stat().st_size
                    except OSError:
                        continue
        return {
            "project_count": len(projects),
            "projects_by_status": by_status,
            "storage_files": total_files,
            "storage_bytes": total_bytes,
        }

    def _resolve_insert_order(self, project: Project, payload: SceneCreate) -> int:
        if payload.after_scene_id:
            after = next((scene for scene in project.scenes if scene.id == payload.after_scene_id), None)
            if after is None:
                raise SceneNotFoundError(payload.after_scene_id)
            return after.order + 1
        if payload.order is not None:
            return min(max(payload.order, 1), len(project.scenes) + 1)
        return len(project.scenes) + 1

    def _sync_scene_source(self, project: Project, scene_id: str) -> None:
        scene = next((item for item in project.scenes if item.id == scene_id), None)
        if not scene:
            return
        if not scene.source_id:
            scene.source_name = None
            scene.source_url = None
            return
        source = next((item for item in project.sources if item.id == scene.source_id), None)
        if source:
            scene.source_name = source.name
            scene.source_url = source.url

    def _normalize_scene_order(self, project: Project) -> None:
        for index, scene in enumerate(project.scenes, start=1):
            scene.order = index
        self._recalculate_scene_timings(project)

    def _recalculate_scene_timings(self, project: Project) -> None:
        start = 0
        for scene in sorted(project.scenes, key=lambda item: item.order):
            scene.start_sec = start
            start += scene.duration_sec

    def _reset_generated_content(self, project: Project) -> None:
        project.sources = []
        project.scenes = []
        project.result = ProjectResult(warnings=list(project.result.warnings))
        project.status = ProjectStatus.draft

    def _clear_render_outputs(self, project: Project) -> None:
        project.result.final_video_path = None
        project.result.description_path = None
        project.result.sources_path = None
        project.result.storyboard_path = None
        project.result.thumbnail_prompt_path = None
        project.result.thumbnail_path = None
        project.result.title_options_path = None
        project.result.youtube_metadata_path = None
        project.result.quality_report_path = None
        project.result.render_manifest_path = None
        project.result.export_package_path = None
