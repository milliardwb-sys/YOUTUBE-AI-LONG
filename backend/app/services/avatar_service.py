from __future__ import annotations

import time
from pathlib import Path

from app.config import Settings
from app.models import Project, Scene
from app.services.providers.base import ProviderUnavailable
from app.services.providers.heygen_provider import HeyGenAvatarProvider
from app.utils.files import ensure_dir, write_json


AVATAR_SCENE_TYPES = {"avatar_fullscreen", "avatar_pip", "screen_demo", "cta"}


class AvatarService:
    """Prepare real avatar assets through HeyGen when configured.

    Local/offline mode still works: the service writes an avatar manifest and
    keeps placeholder visuals if HeyGen credentials are not configured.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def prepare_avatar_overlay(self, project: Project, project_dir: Path) -> Project:
        avatar_dir = ensure_dir(project_dir / "assets" / "avatar")
        scenes = [scene for scene in project.scenes if self._needs_avatar(scene)]
        manifest: dict[str, object] = {
            "provider": "heygen",
            "configured": bool(self.settings.heygen_api_key and self.settings.heygen_avatar_id),
            "project_id": project.id,
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
                manifest["scenes"].append(self._scene_manifest(scene, status="placeholder"))
            self._write_manifest(project, avatar_dir, manifest)
            project.touch("avatar_placeholder_ready")
            return project

        manifest["status"] = "submitted"
        for scene in scenes:
            try:
                if scene.avatar_video_id:
                    details = provider.get_video(scene.avatar_video_id)
                else:
                    details = provider.create_avatar_video(project, scene)
                self._apply_heygen_details(scene, details, avatar_dir)
                if self.settings.heygen_poll_seconds > 0 and scene.avatar_video_id:
                    self._poll_until_ready(provider, scene, avatar_dir)
                manifest["scenes"].append(self._scene_manifest(scene, status=scene.avatar_video_status or "submitted"))
            except Exception as exc:  # noqa: BLE001
                self._add_warning(project, f"HeyGen scene {scene.order} failed; placeholder avatar used: {exc}")
                manifest["scenes"].append(self._scene_manifest(scene, status="failed", error=str(exc)))

        self._write_manifest(project, avatar_dir, manifest)
        project.touch("avatar_prepared")
        return project

    def _needs_avatar(self, scene: Scene) -> bool:
        return scene.avatar_visible and scene.visual_type in AVATAR_SCENE_TYPES

    def _apply_heygen_details(self, scene: Scene, details: dict, avatar_dir: Path) -> None:
        video_id = details.get("video_id") or details.get("id")
        status = details.get("status")
        video_url = details.get("video_url") or details.get("captioned_video_url")
        if video_id:
            scene.avatar_video_id = str(video_id)
        if status:
            scene.avatar_video_status = str(status)
        if video_url:
            scene.avatar_video_url = str(video_url)
        failure = details.get("failure_message") or details.get("failure_code")
        if failure and not status:
            scene.avatar_video_status = "failed"
        if scene.avatar_video_status == "completed" and scene.avatar_video_url and not scene.avatar_video_path:
            output_path = avatar_dir / f"scene_{scene.order:03d}_heygen.mp4"
            try:
                HeyGenAvatarProvider(self.settings).download_video(scene.avatar_video_url, output_path)
                scene.avatar_video_path = str(output_path)
            except Exception:  # noqa: BLE001
                # Download can be retried later; keep the provider URL in the manifest.
                pass

    def _poll_until_ready(self, provider: HeyGenAvatarProvider, scene: Scene, avatar_dir: Path) -> None:
        deadline = time.time() + self.settings.heygen_poll_seconds
        while time.time() < deadline:
            details = provider.get_video(scene.avatar_video_id or "")
            self._apply_heygen_details(scene, details, avatar_dir)
            if scene.avatar_video_status in {"completed", "failed"}:
                return
            time.sleep(5)

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

    def _write_manifest(self, project: Project, avatar_dir: Path, manifest: dict[str, object]) -> None:
        manifest_path = avatar_dir / "avatar_manifest.json"
        write_json(manifest_path, manifest)
        project.result.avatar_manifest_path = str(manifest_path)

    def _add_warning(self, project: Project, warning: str) -> None:
        if warning not in project.result.warnings:
            project.result.warnings.append(warning)
