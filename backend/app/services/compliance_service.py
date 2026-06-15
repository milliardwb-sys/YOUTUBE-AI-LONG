from __future__ import annotations

from app.models import Project, SourceKind, VisualMode, VoiceProviderName


class ComplianceError(ValueError):
    pass


class ComplianceService:
    """Минимальный guardrail для MVP.

    Модуль не заменяет юридическую экспертизу. Его задача — не дать pipeline
    уйти в запрещённую продуктовую логику: скачивание/маскировка чужих YouTube-кадров.
    """

    blocked_phrases = (
        "скачать чужой youtube",
        "скачивать чужие ролики",
        "замаскировать чужой кадр",
        "чтобы автор не понял",
        "обойти content id",
        "удалить водяной знак",
        "перерисуй чужой кадр",
        "сделай неузнаваемым чужой кадр",
        "обход авторских прав",
        "обойти авторские права",
    )

    def validate_project(self, project: Project) -> list[str]:
        text = f"{project.topic} {project.audience} {' '.join(project.source_urls)}".lower()
        for phrase in self.blocked_phrases:
            if phrase in text:
                raise ComplianceError(
                    "Проект похож на запрос по маскировке/переработке чужого контента. "
                    "MVP поддерживает только оригинальные AI-слайды, официальные сайты, "
                    "ваши материалы и разрешённые источники."
                )

        warnings: list[str] = []
        if project.visual_mode == VisualMode.official_sites_plus_ai:
            warnings.append(
                "Используются скриншоты/карточки официальных сайтов. Перед публикацией проверьте "
                "условия сайтов, бренд-гайды и уместность использования в обзоре."
            )
        if any("youtube.com" in url.lower() or "youtu.be" in url.lower() for url in project.source_urls):
            raise ComplianceError(
                "source_urls не должны ссылаться на чужие YouTube-ролики. Для анализа конкурентов "
                "используйте отдельный research-only режим без извлечения кадров."
            )
        if project.avatar_enabled:
            warnings.append(
                "Аватар включён в настройках. Текущий MVP содержит placeholder; для production нужен "
                "провайдер аватара и согласие пользователя на использование likeness."
            )
        if project.voice_provider != VoiceProviderName.placeholder:
            warnings.append(
                "Включён синтетический голос. Для production нужно хранить согласие пользователя "
                "на voice clone/AI-озвучку и проверять disclosure при публикации."
            )
        if project.script_provider.value != "template":
            warnings.append(
                "Сценарий может быть сгенерирован LLM-провайдером. Перед публикацией нужна ручная "
                "проверка фактов, названий платформ, цен и ссылок."
            )
        if project.burn_subtitles:
            warnings.append(
                "Burned-in subtitles включены: проверьте, что субтитры не перекрывают аватар и важные элементы слайда."
            )
        for source in project.sources:
            if source.kind == SourceKind.ai_generated_fallback:
                warnings.append(
                    f"Источник {source.name} является fallback-карточкой, а не реальным скриншотом сайта."
                )
        return self._dedupe(warnings)

    def _dedupe(self, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            if value not in result:
                result.append(value)
        return result
