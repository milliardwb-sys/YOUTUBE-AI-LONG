from __future__ import annotations

import math
import wave
from pathlib import Path

from app.config import Settings
from app.errors import PipelinePreconditionError
from app.models import Project, ProjectStatus, VoiceProviderName
from app.services.providers.factory import make_tts_provider
from app.utils.files import ensure_dir, write_json, write_text
from app.utils.text import escape_srt, to_srt_timestamp, to_vtt_timestamp


class VoiceService:
    """Voice module v0.3 with placeholder and optional OpenAI TTS."""

    sample_rate = 44100

    def __init__(self, settings: Settings):
        self.settings = settings

    def generate_voice(self, project: Project, project_dir: Path) -> Project:
        if not project.scenes:
            raise PipelinePreconditionError("Script is empty. Run generate-script first.")
        audio_dir = ensure_dir(project_dir / "audio")
        manifest: dict = {
            "project_id": project.id,
            "voice_provider_requested": project.voice_provider,
            "voice_provider_used": "placeholder",
            "voice_id": project.voice_id,
            "scenes": [],
        }

        provider = None
        if project.voice_provider == VoiceProviderName.openai:
            try:
                provider = make_tts_provider(self.settings, project.voice_provider)
                manifest["voice_provider_used"] = "openai"
            except Exception as exc:  # noqa: BLE001
                warning = f"TTS provider failed to initialize; placeholder audio was used: {exc}"
                if warning not in project.result.warnings:
                    project.result.warnings.append(warning)

        for scene in project.scenes:
            audio_path = audio_dir / f"scene_{scene.order:03d}.wav"
            used_provider = manifest["voice_provider_used"]
            if provider is not None:
                try:
                    chunk_count = self._synthesize_with_chunks(provider, scene.narration, audio_path, project.voice_id)
                    duration = self._wav_duration_seconds(audio_path)
                    if duration:
                        scene.duration_sec = max(5, int(math.ceil(duration)))
                except Exception as exc:  # noqa: BLE001
                    warning = f"TTS failed for scene {scene.order}; placeholder audio was used: {exc}"
                    if warning not in project.result.warnings:
                        project.result.warnings.append(warning)
                    used_provider = "placeholder"
                    self._write_placeholder_wav(audio_path, scene.duration_sec, scene.order)
            else:
                self._write_placeholder_wav(audio_path, scene.duration_sec, scene.order)

            scene.audio_path = str(audio_path)
            manifest["scenes"].append(
                {
                    "scene_id": scene.id,
                    "order": scene.order,
                    "audio_path": str(audio_path),
                    "duration_sec": scene.duration_sec,
                    "provider_used": used_provider,
                    "characters": len(scene.narration),
                    "chunks": chunk_count if provider is not None and used_provider == "openai" else 1,
                }
            )

        self._recalculate_scene_timings(project)
        self._write_subtitles(project, project_dir)
        manifest_path = ensure_dir(project_dir / "exports") / "voice_manifest.json"
        write_json(manifest_path, manifest)
        project.result.voice_manifest_path = str(manifest_path)
        project.status = ProjectStatus.voice_ready
        project.error = None
        project.touch("voice_ready")
        return project

    def _write_placeholder_wav(self, path: Path, duration_sec: int, seed: int) -> None:
        ensure_dir(path.parent)
        amplitude = 250
        frequency = 220 + (seed % 6) * 25
        total_samples = int(self.sample_rate * duration_sec)
        with wave.open(str(path), "w") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            for i in range(total_samples):
                if i < self.sample_rate // 4:
                    value = int(amplitude * math.sin(2 * math.pi * frequency * i / self.sample_rate))
                else:
                    value = 0
                wav.writeframesraw(value.to_bytes(2, byteorder="little", signed=True))

    def _synthesize_with_chunks(self, provider, text: str, output_path: Path, voice_id: str | None) -> int:
        chunks = self._split_for_tts(text, self.settings.max_openai_tts_chars)
        if len(chunks) == 1:
            provider.synthesize(chunks[0], output_path, voice_id=voice_id)
            return 1

        part_paths: list[Path] = []
        for index, chunk in enumerate(chunks, start=1):
            part_path = output_path.with_name(f"{output_path.stem}_part_{index:03d}{output_path.suffix}")
            provider.synthesize(chunk, part_path, voice_id=voice_id)
            part_paths.append(part_path)
        self._merge_wav_files(part_paths, output_path)
        for part_path in part_paths:
            part_path.unlink(missing_ok=True)
        return len(chunks)

    def _split_for_tts(self, text: str, max_chars: int) -> list[str]:
        text = text.strip()
        if len(text) <= max_chars:
            return [text]
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for word in text.split():
            extra = len(word) + (1 if current else 0)
            if current and current_len + extra > max_chars:
                chunks.append(" ".join(current))
                current = [word]
                current_len = len(word)
            else:
                current.append(word)
                current_len += extra
        if current:
            chunks.append(" ".join(current))
        return chunks or [text[:max_chars]]

    def _merge_wav_files(self, wav_paths: list[Path], output_path: Path) -> None:
        with wave.open(str(wav_paths[0]), "rb") as first:
            params = first.getparams()

        with wave.open(str(output_path), "wb") as output:
            output.setparams(params)
            for wav_path in wav_paths:
                with wave.open(str(wav_path), "rb") as source:
                    if source.getnchannels() != params.nchannels:
                        raise RuntimeError(f"WAV channel mismatch: {wav_path}")
                    if source.getsampwidth() != params.sampwidth:
                        raise RuntimeError(f"WAV sample width mismatch: {wav_path}")
                    if source.getframerate() != params.framerate:
                        raise RuntimeError(f"WAV sample rate mismatch: {wav_path}")
                    output.writeframes(source.readframes(source.getnframes()))

    def _wav_duration_seconds(self, path: Path) -> float | None:
        try:
            with wave.open(str(path), "rb") as wav:
                frames = wav.getnframes()
                rate = wav.getframerate()
                if rate <= 0:
                    return None
                return frames / float(rate)
        except Exception:  # noqa: BLE001
            return None

    def _recalculate_scene_timings(self, project: Project) -> None:
        start = 0
        for scene in sorted(project.scenes, key=lambda item: item.order):
            scene.start_sec = start
            start += scene.duration_sec

    def _write_subtitles(self, project: Project, project_dir: Path) -> None:
        srt_lines: list[str] = []
        vtt_lines: list[str] = ["WEBVTT", ""]
        for idx, scene in enumerate(project.scenes, start=1):
            start = scene.start_sec
            end = scene.start_sec + scene.duration_sec
            clean_text = escape_srt(scene.narration)

            srt_lines.append(str(idx))
            srt_lines.append(f"{to_srt_timestamp(start)} --> {to_srt_timestamp(end)}")
            srt_lines.append(clean_text)
            srt_lines.append("")

            vtt_lines.append(f"{to_vtt_timestamp(start)} --> {to_vtt_timestamp(end)}")
            vtt_lines.append(clean_text)
            vtt_lines.append("")

        exports_dir = ensure_dir(project_dir / "exports")
        subtitles_path = exports_dir / "subtitles.srt"
        captions_vtt_path = exports_dir / "captions.vtt"
        write_text(subtitles_path, "\n".join(srt_lines))
        write_text(captions_vtt_path, "\n".join(vtt_lines))
        project.result.subtitles_path = str(subtitles_path)
        project.result.captions_vtt_path = str(captions_vtt_path)
