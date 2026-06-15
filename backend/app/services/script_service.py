from __future__ import annotations

from app.config import Settings
from app.models import Project, ProjectStatus, Scene, ScriptProviderName, VideoStyle, VisualMode
from app.services.providers.base import ProviderUnavailable
from app.services.providers.factory import make_llm_provider


class ScriptService:
    """Сценарный модуль v0.3.

    По умолчанию работает через template-generator, чтобы MVP запускался офлайн.
    Если в проекте указать script_provider="openai" и задать OPENAI_API_KEY,
    сервис попробует получить живой сценарий через LLMProvider. При ошибке будет
    безопасный fallback на template-generator с warning в project.result.warnings.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def generate_script(self, project: Project) -> Project:
        if project.script_provider == ScriptProviderName.openai:
            try:
                provider = make_llm_provider(self.settings, project.script_provider)
                scenes = provider.generate_scenes(project)
                project.scenes = self._normalize_provider_scenes(project, scenes)
                project.status = ProjectStatus.script_ready
                project.error = None
                project.touch("script_ready_openai")
                return project
            except Exception as exc:  # noqa: BLE001 - fallback должен сохранить UX MVP
                warning = f"LLM provider failed; template script was used instead: {exc}"
                if warning not in project.result.warnings:
                    project.result.warnings.append(warning)

        project.scenes = self._build_template_scenes(project)
        project.status = ProjectStatus.script_ready
        project.error = None
        project.touch("script_ready_template")
        return project

    def _build_template_scenes(self, project: Project) -> list[Scene]:
        duration_sec = project.duration_minutes * 60
        scene_count = self._scene_count(duration_sec)
        base_duration = max(12, duration_sec // scene_count)

        scene_blueprint = self._blueprint(project.style, scene_count)
        scenes: list[Scene] = []
        start = 0

        for index, item in enumerate(scene_blueprint, start=1):
            is_last = index == len(scene_blueprint)
            duration = duration_sec - start if is_last else base_duration
            duration = max(8, duration)
            visual_type = self._visual_type_for(project, index, item["title"], scene_count)
            narration = self._narration_for(project, index, item["title"], item["goal"])
            on_screen_text = self._screen_text_for(project, index, item["title"])
            scenes.append(
                Scene(
                    order=index,
                    title=item["title"],
                    goal=item["goal"],
                    narration=narration,
                    on_screen_text=on_screen_text,
                    visual_type=visual_type,
                    visual_prompt=self._visual_prompt_for(project, visual_type, item["title"]),
                    notes="Template-generated scene. Replace with LLM provider for production copy.",
                    duration_sec=duration,
                    start_sec=start,
                    avatar_visible=project.avatar_enabled,
                )
            )
            start += duration
        return scenes

    def _normalize_provider_scenes(self, project: Project, scenes: list[Scene]) -> list[Scene]:
        target_total = project.duration_minutes * 60
        scenes = scenes[: self._scene_count(target_total)]
        if not scenes:
            raise ProviderUnavailable("LLM provider returned no scenes")

        base = max(8, target_total // len(scenes))
        start = 0
        normalized: list[Scene] = []
        for index, scene in enumerate(scenes, start=1):
            is_last = index == len(scenes)
            duration = target_total - start if is_last else base
            duration = max(8, duration)
            visual_type = scene.visual_type
            if project.visual_mode == VisualMode.ai_slides_only and visual_type == "screenshot":
                visual_type = "ai_slide"
            scene.order = index
            scene.duration_sec = duration
            scene.start_sec = start
            scene.visual_type = visual_type
            scene.avatar_visible = project.avatar_enabled and scene.avatar_visible
            if not scene.on_screen_text:
                scene.on_screen_text = scene.title
            if not scene.visual_prompt:
                scene.visual_prompt = self._visual_prompt_for(project, visual_type, scene.title)
            normalized.append(scene)
            start += duration
        return normalized

    def _scene_count(self, duration_sec: int) -> int:
        if duration_sec <= 180:
            return 8
        if duration_sec <= 360:
            return 12
        return 16

    def _blueprint(self, style: VideoStyle, count: int) -> list[dict[str, str]]:
        if style == VideoStyle.tutorial:
            titles = [
                ("Хук", "зацепить зрителя и показать результат"),
                ("Что будем делать", "объяснить маршрут ролика"),
                ("Шаг 1", "показать первое действие"),
                ("Шаг 2", "показать второе действие"),
                ("Шаг 3", "показать третье действие"),
                ("Типичные ошибки", "предупредить о частых ошибках"),
                ("Проверка результата", "показать как понять, что всё работает"),
                ("Итог", "закрепить ключевую мысль"),
            ]
        elif style == VideoStyle.top_list:
            titles = [
                ("Хук", "обещать полезную подборку"),
                ("Критерии выбора", "объяснить как сравниваем"),
                ("Вариант 1", "разобрать первый вариант"),
                ("Вариант 2", "разобрать второй вариант"),
                ("Вариант 3", "разобрать третий вариант"),
                ("Вариант 4", "разобрать четвёртый вариант"),
                ("Сравнение", "свести варианты в таблицу"),
                ("Рекомендация", "дать практический вывод"),
            ]
        elif style == VideoStyle.trend_analysis:
            titles = [
                ("Что происходит", "обозначить тренд"),
                ("Почему это важно", "показать последствия"),
                ("Ключевые игроки", "назвать участников рынка"),
                ("Что меняется", "разобрать изменения"),
                ("Риски", "объяснить ограничения"),
                ("Возможности", "показать где можно выиграть"),
                ("Прогноз", "дать сценарий развития"),
                ("Вывод", "сформулировать позицию"),
            ]
        elif style == VideoStyle.sales_video:
            titles = [
                ("Проблема", "назвать боль аудитории"),
                ("Цена бездействия", "усилить актуальность"),
                ("Решение", "предложить подход"),
                ("Как работает", "объяснить механику"),
                ("Преимущества", "дать причины выбрать решение"),
                ("Доказательства", "показать доверие"),
                ("Возражения", "закрыть сомнения"),
                ("Призыв", "дать следующий шаг"),
            ]
        else:
            titles = [
                ("Хук", "быстро объяснить зачем смотреть"),
                ("Контекст", "дать базовое понимание темы"),
                ("Критерии оценки", "объяснить логику сравнения"),
                ("Главная идея", "раскрыть ключевой тезис"),
                ("Практический пример", "показать применение"),
                ("Плюсы", "выделить сильные стороны"),
                ("Минусы", "честно назвать ограничения"),
                ("Вывод", "дать рекомендацию"),
            ]

        while len(titles) < count:
            titles.insert(-1, (f"Дополнение {len(titles)}", "расширить объяснение"))
        return [{"title": title, "goal": goal} for title, goal in titles[:count]]

    def _visual_type_for(self, project: Project, index: int, title: str, scene_count: int) -> str:
        lowered = title.lower()
        if "сравнение" in lowered or "критерии" in lowered:
            return "table"
        if project.visual_mode == VisualMode.official_sites_plus_ai and 3 <= index <= max(3, scene_count - 2):
            return "screenshot"
        if index in {2, scene_count - 1}:
            return "diagram"
        return "ai_slide"

    def _visual_prompt_for(self, project: Project, visual_type: str, title: str) -> str:
        base = f"{project.brand_theme.value} YouTube explainer slide for '{title}' about {project.topic}"
        if visual_type == "screenshot":
            return base + "; use official website screenshot/card with highlight and short labels"
        if visual_type == "table":
            return base + "; clean comparison table, large readable text"
        if visual_type == "diagram":
            return base + "; simple process diagram with arrows"
        return base + "; original AI-style visual, no third-party YouTube frames"

    def _narration_for(self, project: Project, index: int, title: str, goal: str) -> str:
        topic = project.topic
        audience = project.audience
        if project.language == "en":
            return (
                f"Scene {index}. {title}. In this part we discuss {topic}. "
                f"The goal is to {goal} for {audience}. "
                "This is a placeholder narration generated by the MVP core. "
                "Next we can connect a real language model, verified sources, voice cloning and avatar video."
            )
        return (
            f"Сцена {index}. {title}. В этой части разбираем тему: {topic}. "
            f"Задача сцены — {goal} для аудитории: {audience}. "
            "Это черновой текст из MVP-генератора. На следующем этапе сюда подключается "
            "реальная языковая модель, проверенные источники, голос пользователя и аватар."
        )

    def _screen_text_for(self, project: Project, index: int, title: str) -> str:
        if index == 1:
            return project.topic
        return title
