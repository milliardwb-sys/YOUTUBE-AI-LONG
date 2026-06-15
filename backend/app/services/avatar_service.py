from __future__ import annotations

from pathlib import Path

from app.models import Project


class AvatarService:
    """Заготовка под talking-head avatar provider.

    MVP пока не генерирует аватар. В production сюда подключается провайдер:
    HeyGen / D-ID / Tavus / собственный пайплайн.
    """

    def prepare_avatar_overlay(self, project: Project, project_dir: Path) -> Project:
        if project.avatar_enabled:
            project.result.warnings.append(
                "Аватар отмечен как включённый, но avatar provider ещё не подключён."
            )
        return project
