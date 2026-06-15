from __future__ import annotations

from pathlib import Path

from app.models import Project, Scene
from app.services.providers.base import AvatarProvider, LLMProvider, TTSProvider


class MockLLMProvider(LLMProvider):
    def generate_scenes(self, project: Project) -> list[Scene]:
        raise NotImplementedError("Use ScriptService template mode or plug a real LLM provider.")


class MockTTSProvider(TTSProvider):
    def synthesize(self, text: str, output_path: Path, voice_id: str | None = None) -> Path:
        output_path.write_bytes(b"")
        return output_path


class MockAvatarProvider(AvatarProvider):
    def create_talking_head(self, script: str, output_path: Path, avatar_id: str) -> Path:
        raise NotImplementedError("Avatar provider is not enabled in MVP core.")
