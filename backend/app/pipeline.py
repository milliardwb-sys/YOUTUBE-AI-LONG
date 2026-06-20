from __future__ import annotations

from app.models import Project, ProjectStatus
from app.errors import PipelinePreconditionError
from app.services.avatar_service import AvatarService
from app.services.compliance_service import ComplianceError, ComplianceService
from app.services.render_service import RenderService
from app.services.script_service import ScriptService
from app.services.source_service import SourceService
from app.services.visual_service import VisualService
from app.services.voice_service import VoiceService
from app.storage import ProjectStore, SceneNotFoundError


class VideoPipeline:
    def __init__(
        self,
        store: ProjectStore,
        compliance: ComplianceService,
        script: ScriptService,
        sources: SourceService,
        visuals: VisualService,
        voice: VoiceService,
        avatar: AvatarService,
        render: RenderService,
    ):
        self.store = store
        self.compliance = compliance
        self.script = script
        self.sources = sources
        self.visuals = visuals
        self.voice = voice
        self.avatar = avatar
        self.render_service = render

    def generate_script(self, project_id: str) -> Project:
        project = self.store.get(project_id)
        return self._guarded(project, lambda p: self.script.generate_script(p))

    def collect_sources(self, project_id: str) -> Project:
        project = self.store.get(project_id)
        project_dir = self.store.project_dir(project_id)
        return self._guarded(project, lambda p: self.sources.collect_sources(p, project_dir))

    def generate_slides(self, project_id: str) -> Project:
        project = self.store.get(project_id)
        project_dir = self.store.project_dir(project_id)
        return self._guarded(project, lambda p: self.visuals.generate_slides(p, project_dir))

    def regenerate_scene_slide(self, project_id: str, scene_id: str) -> Project:
        project = self.store.get(project_id)
        if not any(scene.id == scene_id for scene in project.scenes):
            raise SceneNotFoundError(scene_id)
        project_dir = self.store.project_dir(project_id)
        return self._guarded(
            project,
            lambda p: self.visuals.regenerate_scene_slide(p, project_dir, scene_id),
        )

    def generate_voice(self, project_id: str) -> Project:
        project = self.store.get(project_id)
        project_dir = self.store.project_dir(project_id)
        return self._guarded(project, lambda p: self.voice.generate_voice(p, project_dir))

    def prepare_avatar(self, project_id: str) -> Project:
        project = self.store.get(project_id)
        project_dir = self.store.project_dir(project_id)
        return self._guarded(project, lambda p: self.avatar.prepare_avatar_overlay(p, project_dir))

    def sync_avatar(self, project_id: str) -> Project:
        project = self.store.get(project_id)
        project_dir = self.store.project_dir(project_id)
        return self._guarded(project, lambda p: self.avatar.sync_avatar_statuses(p, project_dir))

    def retry_avatar_scene(self, project_id: str, scene_id: str) -> Project:
        project = self.store.get(project_id)
        scene = next((item for item in project.scenes if item.id == scene_id), None)
        if scene is None:
            raise SceneNotFoundError(scene_id)
        if not self.avatar.needs_avatar(scene):
            raise PipelinePreconditionError("Scene is not configured for avatar generation")
        project_dir = self.store.project_dir(project_id)
        return self._guarded(project, lambda p: self.avatar.retry_avatar_scene(p, project_dir, scene_id))

    def render(self, project_id: str) -> Project:
        project = self.store.get(project_id)
        project_dir = self.store.project_dir(project_id)
        return self._guarded(project, lambda p: self.render_service.render(p, project_dir))

    def generate_all(self, project_id: str) -> Project:
        project = self.store.get(project_id)
        project_dir = self.store.project_dir(project_id)

        def work(p: Project) -> Project:
            p = self.script.generate_script(p)
            self.store.save(p)
            p = self.sources.collect_sources(p, project_dir)
            self.store.save(p)
            p = self.voice.generate_voice(p, project_dir)
            self.store.save(p)
            p = self.visuals.generate_slides(p, project_dir)
            self.store.save(p)
            p = self.avatar.prepare_avatar_overlay(p, project_dir)
            self.store.save(p)
            p = self.render_service.render(p, project_dir)
            return p

        return self._guarded(project, work)

    def _guarded(self, project: Project, fn) -> Project:
        try:
            warnings = self.compliance.validate_project(project)
            for warning in warnings:
                if warning not in project.result.warnings:
                    project.result.warnings.append(warning)
            project = fn(project)
            warnings = self.compliance.validate_project(project)
            for warning in warnings:
                if warning not in project.result.warnings:
                    project.result.warnings.append(warning)
            self.store.save(project)
            return project
        except ComplianceError as exc:
            project.status = ProjectStatus.failed
            project.error = str(exc)
            project.touch("compliance_failed")
            self.store.save(project)
            return project
        except PipelinePreconditionError as exc:
            project.status = ProjectStatus.failed
            project.error = str(exc)
            project.touch("precondition_failed")
            self.store.save(project)
            return project
        except Exception as exc:  # noqa: BLE001 - ошибка должна попасть в project.json
            project.status = ProjectStatus.failed
            project.error = str(exc)
            project.touch("failed")
            self.store.save(project)
            return project
