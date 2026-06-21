from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import Project, Scene, VideoStyle, VisualMode


SOURCE_VISUAL_TYPES = {"screenshot", "screen_demo"}
AVATAR_VISUAL_TYPES = {"avatar_fullscreen", "avatar_pip", "screen_demo", "cta"}


@dataclass(frozen=True)
class VisualPlanDecision:
    scene_id: str
    scene_order: int
    visual_type: str
    avatar_visible: bool
    source_query: str | None
    visual_prompt: str
    reason: str


class VisualPlanService:
    """Production-oriented visual planner for avatar-led YouTube videos.

    The service is deterministic and works offline. It turns a script into a
    per-scene production brief: layout, avatar usage, source query, and prompt.
    Real search/screenshot providers can then consume this plan, while local
    fallback cards still have enough context to look deliberate.
    """

    def plan_project(self, project: Project) -> list[VisualPlanDecision]:
        decisions: list[VisualPlanDecision] = []
        scene_count = len(project.scenes)
        for index, scene in enumerate(project.scenes, start=1):
            visual_type, reason = self._visual_type_for(project, scene, index, scene_count)
            scene.visual_type = visual_type
            scene.avatar_visible = self._avatar_visible_for(project, scene)
            scene.source_query = self._source_query_for(project, scene)
            scene.visual_prompt = self._visual_prompt_for(project, scene)
            scene.notes = self._notes_for(scene, reason)
            decisions.append(
                VisualPlanDecision(
                    scene_id=scene.id,
                    scene_order=scene.order,
                    visual_type=scene.visual_type,
                    avatar_visible=scene.avatar_visible,
                    source_query=scene.source_query,
                    visual_prompt=scene.visual_prompt or "",
                    reason=reason,
                )
            )
        return decisions

    def _visual_type_for(self, project: Project, scene: Scene, index: int, scene_count: int) -> tuple[str, str]:
        if project.visual_mode == VisualMode.ai_slides_only and scene.visual_type in SOURCE_VISUAL_TYPES:
            return "ai_slide", "visual_mode=ai_slides_only, source visuals are disabled"
        if (scene.source_id or scene.source_query) and scene.visual_type:
            return scene.visual_type, "kept user/source-specific visual type"
        if (scene.notes or "").lower().startswith("manual scene") and scene.visual_type:
            return scene.visual_type, "kept manually inserted scene visual type"
        if project.style == VideoStyle.ai_news_avatar and scene.visual_type in {
            "avatar_fullscreen",
            "avatar_pip",
            "screen_demo",
            "ai_broll",
            "big_caption",
            "cta",
        }:
            return scene.visual_type, "kept scripted ai-news-avatar production beat"

        if project.style == VideoStyle.ai_news_avatar:
            if index == 1:
                return "big_caption", "opening retention hook"
            if index == 2:
                return "avatar_fullscreen", "introduce AI host"
            if index == scene_count:
                return "cta", "final call to action"
            if self._looks_like_takeaway(scene) and index >= scene_count - 1:
                return "big_caption", "takeaway beat"
            if self._looks_like_source_proof(scene):
                return "screen_demo", "scene asks for proof or interface demo"
            if self._looks_like_process(scene):
                return "screen_demo", "scene explains a workflow that benefits from screen demo"
            if self._looks_like_visual_reset(scene):
                return "ai_broll", "retention reset / b-roll beat"
            if index % 5 == 0:
                return "ai_broll", "paced visual reset"
            if index % 2 == 0:
                return "screen_demo", "alternate proof screen in avatar-led video"
            return "avatar_pip", "talking-head explanation over visual board"

        if self._looks_like_table(scene):
            return "table", "comparison or criteria scene"
        if self._looks_like_process(scene):
            return "diagram", "process scene"
        if project.visual_mode == VisualMode.official_sites_plus_ai and 3 <= index <= max(3, scene_count - 2):
            return "screenshot", "official source visual mode"
        return scene.visual_type or "ai_slide", "kept existing/default visual type"

    def _avatar_visible_for(self, project: Project, scene: Scene) -> bool:
        if not project.avatar_enabled:
            return False
        if scene.visual_type in AVATAR_VISUAL_TYPES:
            return True
        if project.style == VideoStyle.ai_news_avatar and scene.visual_type == "ai_broll":
            return True
        return False

    def _source_query_for(self, project: Project, scene: Scene) -> str | None:
        existing = (scene.source_query or "").strip()
        if existing:
            return self._clean_query(existing)
        if scene.visual_type not in SOURCE_VISUAL_TYPES and scene.visual_type != "avatar_pip":
            return None
        query_parts = [project.topic, scene.title, scene.goal]
        entities = self._extract_named_entities(project, scene)
        if entities:
            query_parts.insert(0, " ".join(entities[:3]))
        query_parts.append("official website features pricing dashboard")
        if project.language == "ru":
            query_parts.append("официальный сайт обзор интерфейс")
        return self._clean_query(" ".join(query_parts))

    def _visual_prompt_for(self, project: Project, scene: Scene) -> str:
        existing = (scene.visual_prompt or "").strip()
        if existing and self._prompt_has_production_detail(existing):
            return existing[:700]
        base = existing or f"{scene.title}: {scene.goal}"
        source_hint = f" Source query: {scene.source_query}." if scene.source_query else ""
        templates = {
            "avatar_fullscreen": (
                f"{base}. Fullscreen AI avatar host, clean virtual studio, large Russian captions, "
                "fast YouTube news pacing, safe original background."
            ),
            "avatar_pip": (
                f"{base}. Talking-head avatar in the corner over a proof board, browser cards, "
                "metrics, readable labels, no third-party YouTube footage."
            ),
            "screen_demo": (
                f"{base}.{source_hint} Use official website or product UI screenshot, cursor highlight, "
                "zoom frame, readable Russian overlay, avatar picture-in-picture."
            ),
            "ai_broll": (
                f"{base}. Original AI-generated b-roll: creator workflow, SEO/video automation, "
                "cinematic tech scene, no logos, no copyrighted characters."
            ),
            "big_caption": (
                f"{base}. Huge high-contrast Russian words, retention hook, kinetic title card, "
                "thumbnail energy, clean background."
            ),
            "cta": (
                f"{base}. Final call-to-action screen, comment prompt, subscribe/next-step panel, "
                "avatar picture-in-picture."
            ),
            "screenshot": (
                f"{base}.{source_hint} Official website screenshot/card, highlighted section, readable labels, "
                "source footer."
            ),
            "table": f"{base}. Clean comparison matrix, large readable text, 3-4 rows, creator workflow angle.",
            "diagram": f"{base}. Process diagram with arrows, topic-to-video workflow, clear step labels.",
        }
        return templates.get(scene.visual_type, f"{base}. Original clean YouTube explainer visual.")[:700]

    def _notes_for(self, scene: Scene, reason: str) -> str:
        base = scene.notes or ""
        production_note = f"Visual plan: {reason}; asset_role={scene.visual_type}; source_query={scene.source_query or 'none'}."
        if "Visual plan:" in base:
            base = base.split("Visual plan:", 1)[0].strip()
        return f"{base} {production_note}".strip()[:700]

    def _looks_like_source_proof(self, scene: Scene) -> bool:
        text = self._scene_text(scene)
        return any(
            keyword in text
            for keyword in [
                "смотрим",
                "экран",
                "интерфейс",
                "демо",
                "доказ",
                "сайт",
                "платформ",
                "features",
                "pricing",
                "dashboard",
                "screen",
                "proof",
            ]
        )

    def _looks_like_process(self, scene: Scene) -> bool:
        text = self._scene_text(scene)
        return any(keyword in text for keyword in ["процесс", "workflow", "шаг", "step", "pipeline", "схема", "маршрут"])

    def _looks_like_visual_reset(self, scene: Scene) -> bool:
        text = self._scene_text(scene)
        return any(keyword in text for keyword in ["b-roll", "перебив", "вставка", "визуальный сброс", "ai-вставка"])

    def _looks_like_takeaway(self, scene: Scene) -> bool:
        text = self._scene_text(scene)
        return any(keyword in text for keyword in ["вывод", "итог", "takeaway", "главный инсайт"])

    def _looks_like_table(self, scene: Scene) -> bool:
        text = self._scene_text(scene)
        return any(keyword in text for keyword in ["сравнение", "таблица", "критерии", "matrix", "compare"])

    def _scene_text(self, scene: Scene) -> str:
        return " ".join(
            [
                scene.title or "",
                scene.goal or "",
                scene.on_screen_text or "",
                scene.narration or "",
                scene.notes or "",
            ]
        ).lower()

    def _extract_named_entities(self, project: Project, scene: Scene) -> list[str]:
        text = f"{project.topic} {scene.title} {scene.goal} {scene.narration}"
        matches = re.findall(r"\b[A-Z][A-Za-z0-9.+-]{2,}(?:\s+[A-Z][A-Za-z0-9.+-]{2,})?\b", text)
        known = [
            "HeyGen",
            "Runway",
            "Synthesia",
            "Canva",
            "Pika",
            "CapCut",
            "ElevenLabs",
            "Descript",
            "Ahrefs",
            "Semrush",
            "Surfer SEO",
            "Google Trends",
            "YouTube Studio",
        ]
        lowered = text.lower()
        for name in known:
            if name.lower() in lowered:
                matches.insert(0, name)
        result: list[str] = []
        seen: set[str] = set()
        for match in matches:
            normalized = match.strip()
            key = normalized.lower()
            if key in seen or normalized.lower() in {"new", "scene", "youtube"}:
                continue
            seen.add(key)
            result.append(normalized)
        return result[:5]

    def _clean_query(self, value: str) -> str:
        value = re.sub(r"\s+", " ", value).strip(" .,:;")
        return value[:240]

    def _prompt_has_production_detail(self, prompt: str) -> bool:
        text = prompt.lower()
        return any(keyword in text for keyword in ["screenshot", "avatar", "b-roll", "browser", "cta", "caption", "официаль"])
