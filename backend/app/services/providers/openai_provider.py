from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.config import Settings
from app.models import Project, Scene, VisualMode
from app.services.providers.base import LLMProvider, ProviderUnavailable, TTSProvider


class OpenAILLMProvider(LLMProvider):
    """Optional script provider. Lazy-imported so offline MVP still runs."""

    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise ProviderUnavailable("OPENAI_API_KEY is not configured")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderUnavailable("Install optional dependency: pip install openai") from exc
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model
        self.temperature = settings.openai_temperature

    def generate_scenes(self, project: Project) -> list[Scene]:
        scene_count = self._scene_count(project.duration_minutes * 60)
        visual_policy = (
            "Use screenshot scenes only for official/public product websites. Never use frames from third-party YouTube videos."
            if project.visual_mode == VisualMode.official_sites_plus_ai
            else "Use only original AI slides, tables and diagrams; no screenshots."
        )
        prompt = f"""
Create a YouTube video scene plan as strict JSON.
Language: {project.language}
Topic: {project.topic}
Audience: {project.audience}
Style: {project.style.value}
Duration: {project.duration_minutes} minutes
Scene count: {scene_count}
Visual policy: {visual_policy}
Avatar enabled: {project.avatar_enabled}

Return JSON object:
{{"scenes":[{{"title":"short title","goal":"one sentence goal","narration":"natural voiceover text","on_screen_text":"short overlay text","visual_type":"ai_slide|screenshot|table|diagram","visual_prompt":"specific visual direction","notes":"source/production notes"}}]}}

Rules:
- Return exactly {scene_count} scenes.
- Narration must be original, useful and ready for voiceover.
- For screenshot scenes, describe what official page should be shown, not a video frame.
- Do not mention that you are an AI.
""".strip()
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are a careful YouTube producer. Output valid JSON only."},
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content or "{}"
        payload = self._loads_json(content)
        raw_scenes = payload.get("scenes", [])
        if not isinstance(raw_scenes, list) or not raw_scenes:
            raise RuntimeError("OpenAI response did not contain scenes[]")
        base_duration = max(8, (project.duration_minutes * 60) // len(raw_scenes))
        scenes: list[Scene] = []
        for index, item in enumerate(raw_scenes, start=1):
            if not isinstance(item, dict):
                continue
            visual_type = str(item.get("visual_type") or "ai_slide").strip()
            if visual_type not in {"ai_slide", "screenshot", "table", "diagram"}:
                visual_type = "ai_slide"
            if project.visual_mode == VisualMode.ai_slides_only and visual_type == "screenshot":
                visual_type = "ai_slide"
            scenes.append(
                Scene(
                    order=index,
                    title=self._clean(item.get("title"), f"Сцена {index}") or f"Сцена {index}",
                    goal=self._clean(item.get("goal"), "раскрыть ключевую мысль") or "раскрыть ключевую мысль",
                    narration=self._clean(item.get("narration"), project.topic) or project.topic,
                    on_screen_text=self._clean(item.get("on_screen_text"), item.get("title") or project.topic) or project.topic,
                    visual_type=visual_type,  # type: ignore[arg-type]
                    visual_prompt=self._clean(item.get("visual_prompt"), None),
                    notes=self._clean(item.get("notes"), None),
                    duration_sec=base_duration,
                    avatar_visible=project.avatar_enabled,
                )
            )
        if not scenes:
            raise RuntimeError("OpenAI response produced no valid scenes")
        return scenes

    def _loads_json(self, content: str) -> dict[str, Any]:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, flags=re.S)
            if not match:
                raise
            return json.loads(match.group(0))

    def _clean(self, value: Any, fallback: str | None) -> str | None:
        if value is None:
            return fallback
        text = str(value).strip()
        return text or fallback

    def _scene_count(self, duration_sec: int) -> int:
        if duration_sec <= 180:
            return 8
        if duration_sec <= 360:
            return 12
        return 16


class OpenAITTSProvider(TTSProvider):
    """Optional TTS adapter. Produces WAV files when OPENAI_API_KEY is configured."""

    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise ProviderUnavailable("OPENAI_API_KEY is not configured")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderUnavailable("Install optional dependency: pip install openai") from exc
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_tts_model
        self.default_voice = settings.openai_tts_voice
        self.max_chars = settings.max_openai_tts_chars

    def synthesize(self, text: str, output_path: Path, voice_id: str | None = None) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        text = text.strip()
        if not text:
            raise RuntimeError("Cannot synthesize empty text")
        if len(text) > self.max_chars:
            raise RuntimeError("TTS text exceeds max chars; split before synthesize")
        response = self.client.audio.speech.create(
            model=self.model,
            voice=voice_id or self.default_voice,
            input=text,
            response_format="wav",
        )
        if hasattr(response, "write_to_file"):
            response.write_to_file(str(output_path))
        elif hasattr(response, "read"):
            output_path.write_bytes(response.read())
        elif hasattr(response, "content"):
            output_path.write_bytes(response.content)
        else:
            raise RuntimeError("Unsupported OpenAI TTS response object")
        return output_path
