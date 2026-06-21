from __future__ import annotations

import time
from pathlib import Path

from app.config import Settings
from app.models import Project, Scene
from app.services.providers.base import ProviderUnavailable
from app.services.providers.heygen_provider import HeyGenAvatarProvider
from app.utils.files import ensure_dir, write_json


AVATAR_SCENE_TYPES = {"avatar_fullscreen", "avatar_pip", "screen_demo", "cta"}
READY_STATUSES = {"completed", "complete", "done"}
ACTIVE_STATUSES = {"queued", "pending", "processing", "in_progress", "running", "submitted"}


class AvatarService:
    """Prepare and maintain real avatar assets through HeyGen when configured.

    Local/offline mode still works: the service writes an avatar manifest and
    keeps placeholder visuals if HeyGen credentials are not configured.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def prepare_avatar_overlay(self, project: Project, project_dir: Path) -> Project:
        return self._process_avatar_scenes(project, project_dir, mode="prepare")

    def sync_avatar_statuses(self, project: Project, project_dir: Path) -> Project:
        return self._process_avatar_scenes(project, project_dir, mode="sync")

    def retry_avatar_scene(self, project: Project, project_dir: Path, scene_id: str) -> Project:
        return self._process_avatar_scenes(project, project_dir, mode="retry", only_scene_id=scene_id)

    def needs_avatar(self, scene: Scene) -> bool:
        return scene.avatar_visible and scene.visual_type in AVATAR_SCENE_TYPES

    def apply_webhook_update(self, project: Project, project_dir: Path, video_id: str, details: dict) -> Project:
        avatar_dir = ensure_dir(project_dir / "assets" / "avatar")
        scene = next((item for item in project.scenes if item.avatar_video_id == video_id), None)
        if scene is None:
            raise ValueError(f"Avatar video {video_id} is not attached to this project")
        provider = HeyGenAvatarProvider(self.settings)
        self._apply_heygen_details(provider, scene, {"video_id": video_id, **details}, avatar_dir)
        scenes = [item for item in project.scenes if self.needs_avatar(item)]
        manifest = {
            "provider": "heygen",
            "configured": bool(self.settings.heygen_api_key and self.settings.heygen_avatar_id),
            "project_id": project.id,
            "mode": "webhook",
            "scene_count": len(scenes),
            "status": self._rollup_status([self._scene_manifest(item, status=self._scene_status(item)) for item in scenes]),
            "scenes": [self._scene_manifest(item, status=self._scene_status(item)) for item in scenes],
        }
        self._write_manifest(project, avatar_dir, manifest)
        project.touch("avatar_webhook_synced")
        return project

    def _process_avatar_scenes(
        self,
        project: Project,
        project_dir: Path,
        *,
        mode: str,
        only_scene_id: str | None = None,
    ) -> Project:
        avatar_dir = ensure_dir(project_dir / "assets" / "avatar")
        scenes = [scene for scene in project.scenes if self.needs_avatar(scene)]
        if only_scene_id:
            scenes = [scene for scene in scenes if scene.id == only_scene_id]
        manifest: dict[str, object] = {
            "provider": "heygen",
            "configured": bool(self.settings.heygen_api_key and self.settings.heygen_avatar_id),
            "project_id": project.id,
            "mode": mode,
            "scene_count": len(scenes),
            "scenes": [],
        }

        if not project.avatar_enabled:
            manifest["status"] = "avatar_disabled"
            self._write_manifest(project, avatar_dir, manifest)
            project.touch("avatar_skipped")
            return project

        if not scenes:
            manifest["status"] = "no_avatar_scenes"
            self._write_manifest(project, avatar_dir, manifest)
            project.touch("avatar_skipped")
            return project

        try:
            provider = HeyGenAvatarProvider(self.settings)
        except ProviderUnavailable as exc:
            manifest["status"] = "provider_not_configured"
            self._add_warning(project, f"HeyGen не подключён: {exc}. Используются placeholder-аватары.")
            for scene in scenes:
                if mode == "retry":
                    self._clear_scene_avatar(scene)
                manifest["scenes"].append(self._scene_manifest(scene, status="placeholder"))
            self._write_manifest(project, avatar_dir, manifest)
            project.touch("avatar_placeholder_ready")
            return project

        for scene in scenes:
            try:
                if mode == "retry":
                    self._clear_scene_avatar(scene)
                details = self._next_heygen_details(provider, project, scene, mode)
                if details is None:
                    manifest["scenes"].append(self._scene_manifest(scene, status="not_submitted"))
                    continue
                self._apply_heygen_details(provider, scene, details, avatar_dir)
                if self.settings.heygen_poll_seconds > 0 and scene.avatar_video_id:
                    self._poll_until_ready(provider, scene, avatar_dir)
                manifest["scenes"].append(self._scene_manifest(scene, status=self._scene_status(scene)))
            except Exception as exc:  # noqa: BLE001
                self._add_warning(project, f"HeyGen scene {scene.order} failed; placeholder avatar used: {exc}")
                manifest["scenes"].append(self._scene_manifest(scene, status="failed", error=str(exc)))

        manifest["status"] = self._rollup_status(manifest["scenes"])
        self._write_manifest(project, avatar_dir, manifest)
        project.touch(
            {
                "prepare": "avatar_prepared",
                "sync": "avatar_synced",
                "retry": "avatar_scene_retried",
            }.get(mode, "avatar_prepared")
        )
        return project

    def _next_heygen_details(
        self,
        provider: HeyGenAvatarProvider,
        project: Project,
        scene: Scene,
        mode: str,
    ) -> dict | None:
        if scene.avatar_video_id:
            return provider.get_video(scene.avatar_video_id)
        if mode == "sync":
            return None
        return provider.create_avatar_video(project, scene)

    def _apply_heygen_details(
        self,
        provider: HeyGenAvatarProvider,
        scene: Scene,
        details: dict,
        avatar_dir: Path,
    ) -> None:
        video_id = details.get("video_id") or details.get("id")
        status = details.get("status")
        video_url = details.get("video_url") or details.get("captioned_video_url") or details.get("download_url")
        if video_id:
            scene.avatar_video_id = str(video_id)
        if status:
            scene.avatar_video_status = str(status)
        if video_url:
            scene.avatar_video_url = str(video_url)
        failure = details.get("failure_message") or details.get("failure_code") or details.get("error")
        if failure and not status:
            scene.avatar_video_status = "failed"
        if self._is_ready(scene) and scene.avatar_video_url and not scene.avatar_video_path:
            output_path = avatar_dir / f"scene_{scene.order:03d}_heygen.mp4"
            try:
                provider.download_video(scene.avatar_video_url, output_path)
                scene.avatar_video_path = str(output_path)
            except Exception:  # noqa: BLE001
                # Download can be retried later through sync-avatar; keep the provider URL in the manifest.
                pass

    def _poll_until_ready(self, provider: HeyGenAvatarProvider, scene: Scene, avatar_dir: Path) -> None:
        deadline = time.time() + self.settings.heygen_poll_seconds
        while time.time() < deadline:
            details = provider.get_video(scene.avatar_video_id or "")
            self._apply_heygen_details(provider, scene, details, avatar_dir)
            if self._is_ready(scene) or (scene.avatar_video_status or "").lower() == "failed":
                return
            time.sleep(5)

    def _scene_status(self, scene: Scene) -> str:
        if scene.avatar_video_path:
            return "downloaded"
        if self._is_ready(scene):
            return "ready_remote"
        if scene.avatar_video_status:
            return scene.avatar_video_status
        if scene.avatar_video_id:
            return "submitted"
        return "not_submitted"

    def _rollup_status(self, scene_entries: object) -> str:
        entries = scene_entries if isinstance(scene_entries, list) else []
        statuses = {str(entry.get("status")) for entry in entries if isinstance(entry, dict)}
        if not statuses:
            return "no_avatar_scenes"
        if statuses <= {"downloaded"}:
            return "ready"
        if "failed" in statuses:
            return "has_failures"
        if statuses & ACTIVE_STATUSES or statuses & {"ready_remote", "not_submitted"}:
            return "in_progress"
        if "placeholder" in statuses:
            return "provider_not_configured"
        return "submitted"

    def _scene_manifest(self, scene: Scene, *, status: str, error: str | None = None) -> dict[str, object]:
        return {
            "scene_id": scene.id,
            "scene_order": scene.order,
            "visual_type": scene.visual_type,
            "status": status,
            "error": error,
            "heygen_video_id": scene.avatar_video_id,
            "heygen_status": scene.avatar_video_status,
            "heygen_video_url": scene.avatar_video_url,
            "local_video_path": scene.avatar_video_path,
            "script": scene.narration,
            "notes": (
                "Use this asset as fullscreen avatar or PIP overlay in the final compositor. "
                "Current fallback render keeps static placeholder if the MP4 is not downloaded."
            ),
        }

    def _is_ready(self, scene: Scene) -> bool:
        return (scene.avatar_video_status or "").lower() in READY_STATUSES

    def _clear_scene_avatar(self, scene: Scene) -> None:
        scene.avatar_video_id = None
        scene.avatar_video_status = None
        scene.avatar_video_url = None
        scene.avatar_video_path = None

    def _write_manifest(self, project: Project, avatar_dir: Path, manifest: dict[str, object]) -> None:
        manifest_path = avatar_dir / "avatar_manifest.json"
        write_json(manifest_path, manifest)
        project.result.avatar_manifest_path = str(manifest_path)

    def _add_warning(self, project: Project, warning: str) -> None:
        if warning not in project.result.warnings:
            project.result.warnings.append(warning)
