from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request, urlopen

from app.config import Settings
from app.models import Project, Scene
from app.services.providers.base import ProviderUnavailable


class HeyGenAvatarProvider:
    """Small HeyGen v3 client for avatar scene jobs.

    Official API shape used here:
    - POST /v3/videos creates an avatar video and returns video_id/status.
    - GET /v3/videos/{video_id} returns status, video_url and failure details.
    """

    def __init__(self, settings: Settings):
        if not settings.heygen_api_key:
            raise ProviderUnavailable("HEYGEN_API_KEY is not configured")
        if not settings.heygen_avatar_id:
            raise ProviderUnavailable("HEYGEN_AVATAR_ID is not configured")
        self.settings = settings
        self.base_url = settings.heygen_api_base_url.rstrip("/")

    def create_avatar_video(self, project: Project, scene: Scene) -> dict:
        payload: dict[str, object] = {
            "type": "avatar",
            "avatar_id": self.settings.heygen_avatar_id,
            "title": f"{project.topic[:72]} - scene {scene.order:02d}",
            "resolution": self.settings.heygen_resolution,
            "aspect_ratio": "16:9",
            "remove_background": self.settings.heygen_remove_background,
            "caption": {"file_format": "srt", "style": "default"},
            "output_format": self.settings.heygen_output_format,
            "script": scene.narration,
        }
        if self.settings.heygen_enable_motion_prompt:
            payload["motion_prompt"] = self._motion_prompt(scene)
        if self.settings.heygen_voice_id:
            payload["voice_id"] = self.settings.heygen_voice_id
        response = self._request_json(
            "POST",
            "/v3/videos",
            payload=payload,
            idempotency_key=f"{project.id}:{scene.id}:heygen",
        )
        return response.get("data", response)

    def get_video(self, video_id: str) -> dict:
        response = self._request_json("GET", f"/v3/videos/{video_id}")
        return response.get("data", response)

    def download_video(self, video_url: str, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        request = Request(video_url, headers={"User-Agent": "AI Video Studio"})
        with urlopen(request, timeout=120) as response:  # noqa: S310 - provider-returned video asset
            output_path.write_bytes(response.read())
        return output_path

    def _request_json(self, method: str, path: str, *, payload: dict | None = None, idempotency_key: str | None = None) -> dict:
        data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8") if payload is not None else None
        headers = {
            "X-Api-Key": self.settings.heygen_api_key or "",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key[:255]
        request = Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=60) as response:  # noqa: S310 - configured HeyGen API endpoint
                body = response.read().decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"HeyGen API request failed: {method} {path}: {exc}") from exc
        try:
            return json.loads(body) if body else {}
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"HeyGen API returned non-JSON response: {body[:300]}") from exc

    def _motion_prompt(self, scene: Scene) -> str:
        if scene.visual_type == "avatar_fullscreen":
            return "Confident presenter, direct eye contact, calm hand gestures, news anchor energy."
        if scene.visual_type in {"avatar_pip", "screen_demo"}:
            return "Concise explainer tone, subtle gestures, pointing as if referencing an on-screen demo."
        if scene.visual_type == "cta":
            return "Friendly closing, encouraging viewer to comment and take the next step."
        return "Natural presenter motion for a short AI news video."
