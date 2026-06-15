from __future__ import annotations

from app.config import Settings
from app.models import ScriptProviderName, VoiceProviderName
from app.services.providers.base import LLMProvider, ProviderUnavailable, TTSProvider
from app.services.providers.openai_provider import OpenAILLMProvider, OpenAITTSProvider


def make_llm_provider(settings: Settings, name: ScriptProviderName) -> LLMProvider:
    if name == ScriptProviderName.openai:
        return OpenAILLMProvider(settings)
    raise ProviderUnavailable(f"Unsupported LLM provider: {name}")


def make_tts_provider(settings: Settings, name: VoiceProviderName) -> TTSProvider:
    if name == VoiceProviderName.openai:
        return OpenAITTSProvider(settings)
    raise ProviderUnavailable(f"Unsupported TTS provider: {name}")
