from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.models import Project, Scene


class ProviderUnavailable(RuntimeError):
    pass


class LLMProvider(ABC):
    @abstractmethod
    def generate_scenes(self, project: Project) -> list[Scene]:
        raise NotImplementedError


class TTSProvider(ABC):
    @abstractmethod
    def synthesize(self, text: str, output_path: Path, voice_id: str | None = None) -> Path:
        raise NotImplementedError


class AvatarProvider(ABC):
    @abstractmethod
    def create_talking_head(self, script: str, output_path: Path, avatar_id: str) -> Path:
        raise NotImplementedError
