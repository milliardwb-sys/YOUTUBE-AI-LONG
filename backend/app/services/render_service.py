from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image, ImageDraw, ImageFont

from app.config import Settings
from app.errors import PipelinePreconditionError
from app.models import Project, ProjectStatus
from app.utils.files import ensure_dir, write_json, write_text
from app.utils.security import ensure_within_directory
from app.utils.text import wrap_text


class RenderService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.font_title = self._load_font(84)
        self.font_regular = self._load_font(48)
        self.font_small = self._load_font(30)
        self.font_tiny = self._load_font(24)

    def render(self, project: Project, project_dir: Path) -> Project:
        render_dir = ensure_dir(project_dir / "video")
        manifest_path = project_dir / "exports" / "render_manifest.json"
        ensure_dir(manifest_path.parent)

        project.status = ProjectStatus.rendering
        project.touch("rendering")

        manifest = {
            "project_id": project.id,
            "topic": project.topic,
            "width": self.settings.render_width,
            "height": self.settings.render_height,
            "fps": self.settings.render_fps,
            "visual_mode": project.visual_mode,
            "brand_theme": project.brand_theme,
            "script_provider": project.script_provider,
            "voice_provider": project.voice_provider,
            "avatar_enabled": project.avatar_enabled,
            "burn_subtitles": project.burn_subtitles,
            "scenes": [scene.model_dump(mode="json") for scene in project.scenes],
            "sources": [source.model_dump(mode="json") for source in project.sources],
        }
        write_json(manifest_path, manifest)
        project.result.render_manifest_path = str(manifest_path)

        if not project.scenes:
            raise PipelinePreconditionError("Project has no scenes")
        for scene in project.scenes:
            if not scene.visual_path or not scene.audio_path:
                raise PipelinePreconditionError(f"Scene {scene.order} has no visual/audio path")
            self._safe_existing_project_file(project, project_dir, scene.visual_path, f"Scene {scene.order} visual", strict=True)
            self._safe_existing_project_file(project, project_dir, scene.audio_path, f"Scene {scene.order} audio", strict=True)

        ffmpeg_bin = self.resolve_ffmpeg_bin()
        if not ffmpeg_bin:
            project.status = ProjectStatus.failed
            project.error = "FFmpeg не найден в PATH. Manifest создан, но MP4 не собран."
            project.touch("ffmpeg_missing")
            self._write_exports(project, project_dir)
            self._create_export_package(project, project_dir)
            return project

        slideshow_file = render_dir / "slides_concat.txt"
        self._write_slideshow_concat(project, project_dir, slideshow_file)

        full_audio = render_dir / "full_audio.wav"
        audio_paths = [
            self._safe_existing_project_file(project, project_dir, scene.audio_path, f"Scene {scene.order} audio", strict=True)
            for scene in project.scenes
        ]
        self._merge_wav_files(audio_paths, full_audio)

        final_video = render_dir / "final.mp4"
        self._render_slideshow(project, slideshow_file, full_audio, final_video, ffmpeg_bin)

        project.result.final_video_path = str(final_video)
        self._write_exports(project, project_dir)
        self._create_export_package(project, project_dir)
        project.status = ProjectStatus.completed
        project.error = None
        project.touch("completed")
        return project

    def _write_slideshow_concat(self, project: Project, project_dir: Path, concat_file: Path) -> None:
        lines: list[str] = []
        for scene in project.scenes:
            image_path = self._safe_existing_project_file(
                project, project_dir, scene.visual_path, f"Scene {scene.order} visual", strict=True
            ).resolve().as_posix()
            lines.append(f"file '{image_path}'")
            lines.append(f"duration {scene.duration_sec}")
        last_path = self._safe_existing_project_file(
            project, project_dir, project.scenes[-1].visual_path, "Last scene visual", strict=True
        ).resolve().as_posix()
        lines.append(f"file '{last_path}'")
        concat_file.write_text("\n".join(lines), encoding="utf-8")

    def _merge_wav_files(self, wav_paths: list[Path], output_path: Path) -> None:
        if not wav_paths:
            raise RuntimeError("No WAV files to merge")

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

    def resolve_ffmpeg_bin(self) -> str | None:
        configured = shutil.which(self.settings.ffmpeg_bin)
        if configured:
            return configured
        try:
            import imageio_ffmpeg
        except ImportError:
            return None
        try:
            candidate = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:  # noqa: BLE001
            return None
        if candidate and Path(candidate).exists():
            return str(candidate)
        return None

    def _resolve_ffmpeg_bin(self) -> str | None:
        return self.resolve_ffmpeg_bin()

    def _render_slideshow(
        self,
        project: Project,
        concat_file: Path,
        audio_path: Path,
        final_video: Path,
        ffmpeg_bin: str,
    ) -> None:
        video_filter = f"scale={self.settings.render_width}:{self.settings.render_height},format=yuv420p"
        if project.burn_subtitles:
            if project.result.subtitles_path and Path(project.result.subtitles_path).exists():
                escaped = Path(project.result.subtitles_path).resolve().as_posix().replace("'", "\\'")
                video_filter = f"{video_filter},subtitles='{escaped}'"
            else:
                warning = "burn_subtitles=true, but subtitles file was not found; video rendered without burned captions."
                if warning not in project.result.warnings:
                    project.result.warnings.append(warning)

        cmd = [
            ffmpeg_bin,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-i",
            str(audio_path),
            "-vf",
            video_filter,
            "-r",
            str(self.settings.render_fps),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-tune",
            "stillimage",
            "-c:a",
            "aac",
            "-shortest",
            str(final_video),
        ]
        self._run(cmd)

    def _run(self, cmd: list[str]) -> None:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.settings.render_timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"FFmpeg command timed out after {self.settings.render_timeout_seconds} seconds"
            ) from exc
        if result.returncode != 0:
            raise RuntimeError(
                "FFmpeg command failed:\n"
                + " ".join(cmd)
                + "\nSTDERR:\n"
                + result.stderr[-4000:]
            )

    def _write_exports(self, project: Project, project_dir: Path) -> None:
        exports_dir = ensure_dir(project_dir / "exports")
        description_path = exports_dir / "description.txt"
        sources_path = exports_dir / "sources.json"
        storyboard_path = exports_dir / "storyboard.json"
        thumbnail_prompt_path = exports_dir / "thumbnail_prompt.txt"
        thumbnail_path = exports_dir / "thumbnail.png"
        title_options_path = exports_dir / "title_options.txt"
        youtube_metadata_path = exports_dir / "youtube_metadata.json"
        quality_report_path = exports_dir / "quality_report.json"

        write_text(description_path, self._make_description(project))
        write_json(sources_path, self._make_sources_export(project))
        write_json(storyboard_path, self._make_storyboard(project))
        write_text(thumbnail_prompt_path, self._make_thumbnail_prompt(project))
        write_text(title_options_path, "\n".join(self._make_title_options(project)) + "\n")
        write_json(youtube_metadata_path, self._make_youtube_metadata(project))
        write_json(quality_report_path, self._make_quality_report(project))
        self._render_thumbnail(project, thumbnail_path)

        project.result.description_path = str(description_path)
        project.result.sources_path = str(sources_path)
        project.result.storyboard_path = str(storyboard_path)
        project.result.thumbnail_prompt_path = str(thumbnail_prompt_path)
        project.result.thumbnail_path = str(thumbnail_path)
        project.result.title_options_path = str(title_options_path)
        project.result.youtube_metadata_path = str(youtube_metadata_path)
        project.result.quality_report_path = str(quality_report_path)

    def _create_export_package(self, project: Project, project_dir: Path) -> None:
        exports_dir = ensure_dir(project_dir / "exports")
        package_path = exports_dir / "result_package.zip"
        files = [
            project.result.final_video_path,
            project.result.subtitles_path,
            project.result.captions_vtt_path,
            project.result.description_path,
            project.result.sources_path,
            project.result.storyboard_path,
            project.result.thumbnail_prompt_path,
            project.result.thumbnail_path,
            project.result.title_options_path,
            project.result.youtube_metadata_path,
            project.result.quality_report_path,
            project.result.voice_manifest_path,
            project.result.render_manifest_path,
        ]
        with ZipFile(package_path, "w", compression=ZIP_DEFLATED) as archive:
            for file_value in files:
                file_path = self._safe_existing_project_file(project, project_dir, file_value, "Export artifact")
                if file_path:
                    archive.write(file_path, arcname=file_path.name)
            for scene in project.scenes:
                file_path = self._safe_existing_project_file(project, project_dir, scene.visual_path, f"Scene {scene.order} visual")
                if file_path:
                    archive.write(file_path, arcname=f"slides/{file_path.name}")
            for scene in project.scenes:
                file_path = self._safe_existing_project_file(project, project_dir, scene.audio_path, f"Scene {scene.order} audio")
                if file_path:
                    archive.write(file_path, arcname=f"audio/{file_path.name}")
            for source in project.sources:
                file_path = self._safe_existing_project_file(project, project_dir, source.screenshot_path, f"Source {source.id} screenshot")
                if file_path:
                    archive.write(file_path, arcname=f"sources/{file_path.name}")
        project.result.export_package_path = str(package_path)

    def _safe_existing_project_file(
        self,
        project: Project,
        project_dir: Path,
        path_value: str | None,
        label: str,
        *,
        strict: bool = False,
    ) -> Path | None:
        if not path_value:
            return None
        try:
            path = ensure_within_directory(project_dir, Path(path_value))
        except (OSError, ValueError) as exc:
            message = f"{label} path escapes project directory"
            if strict:
                raise RuntimeError(message) from exc
            warning = f"{message}; skipped from export package."
            if warning not in project.result.warnings:
                project.result.warnings.append(warning)
            return None
        if not path.is_file():
            if strict:
                raise RuntimeError(f"{label} file is missing: {path_value}")
            return None
        return path

    def _make_description(self, project: Project) -> str:
        chapters: list[str] = []
        for scene in project.scenes:
            mm = scene.start_sec // 60
            ss = scene.start_sec % 60
            chapters.append(f"{mm:02d}:{ss:02d} — {scene.title}")

        sources_text = ""
        if project.sources:
            sources_text = "\n\nИсточники и визуальные референсы:\n" + "\n".join(
                f"- {source.name}: {source.url}" for source in project.sources
            )

        return (
            f"{project.topic}\n\n"
            "Сгенерировано в AI Video Studio MVP.\n\n"
            "Таймкоды:\n"
            + "\n".join(chapters)
            + sources_text
            + "\n\n"
            "Примечание: текущая версия использует оригинальные AI-слайды, карточки/скриншоты "
            "официальных источников и подключаемые voice/script providers. Чужие YouTube-кадры "
            "не используются. Перед публикацией проверьте факты, лицензии и disclosure для AI-аватара/голоса.\n"
        )

    def _make_sources_export(self, project: Project) -> dict:
        return {
            "policy": (
                "Project uses original AI slides, user-provided URLs, official/public pages, "
                "or offline fallback cards. It does not use frames from third-party YouTube videos."
            ),
            "visual_mode": project.visual_mode,
            "sources": [source.model_dump(mode="json") for source in project.sources],
            "warnings": project.result.warnings,
        }

    def _make_storyboard(self, project: Project) -> dict:
        return {
            "project_id": project.id,
            "topic": project.topic,
            "duration_minutes": project.duration_minutes,
            "actual_duration_sec": sum(scene.duration_sec for scene in project.scenes),
            "style": project.style,
            "language": project.language,
            "brand_theme": project.brand_theme,
            "script_provider": project.script_provider,
            "voice_provider": project.voice_provider,
            "scenes": [scene.model_dump(mode="json") for scene in project.scenes],
        }

    def _make_thumbnail_prompt(self, project: Project) -> str:
        source_names = ", ".join(source.name for source in project.sources[:4]) or "AI slides"
        if project.language == "en":
            return (
                f"Create a high-contrast YouTube thumbnail for a video titled: {project.topic}. "
                f"Show 2-3 large readable words, modern tech style, clean SaaS cards, sources: {source_names}. "
                "No copyrighted screenshots from third-party YouTube videos."
            )
        return (
            f"Создай контрастную YouTube-обложку для ролика: {project.topic}. "
            f"2–3 крупных читаемых слова, современный tech/SaaS стиль, визуальные карточки: {source_names}. "
            "Не использовать кадры из чужих YouTube-видео."
        )

    def _make_title_options(self, project: Project) -> list[str]:
        topic = project.topic.rstrip(" .")
        if project.language == "en":
            return [
                topic,
                f"{topic}: What Actually Matters",
                f"I Tested the Best Options for {topic}",
                f"How to Choose: {topic}",
                f"The Practical Guide to {topic}",
            ]
        return [
            topic,
            f"{topic}: что реально важно",
            f"Я разобрал(а) лучшие варианты: {topic}",
            f"Как выбрать: {topic}",
            f"Практический гид: {topic}",
        ]

    def _make_youtube_metadata(self, project: Project) -> dict:
        return {
            "title_options": self._make_title_options(project),
            "recommended_title": self._make_title_options(project)[0],
            "description": self._make_description(project),
            "tags": self._make_tags(project),
            "chapters": [
                {"time": f"{scene.start_sec // 60:02d}:{scene.start_sec % 60:02d}", "title": scene.title}
                for scene in project.scenes
            ],
            "ai_disclosure_note": (
                "Check YouTube upload disclosure settings if this video uses realistic AI avatar, "
                "synthetic voice, or altered realistic content."
            ),
        }

    def _make_quality_report(self, project: Project) -> dict:
        missing_visuals = [scene.id for scene in project.scenes if not scene.visual_path or not Path(scene.visual_path).exists()]
        missing_audio = [scene.id for scene in project.scenes if not scene.audio_path or not Path(scene.audio_path).exists()]
        fallback_sources = [source.id for source in project.sources if source.status == "fallback_card"]
        captured_sources = [source.id for source in project.sources if source.status == "captured"]
        return {
            "project_id": project.id,
            "status": project.status,
            "topic": project.topic,
            "scene_count": len(project.scenes),
            "source_count": len(project.sources),
            "target_duration_sec": project.duration_minutes * 60,
            "actual_duration_sec": sum(scene.duration_sec for scene in project.scenes),
            "script_provider": project.script_provider,
            "voice_provider": project.voice_provider,
            "visual_mode": project.visual_mode,
            "brand_theme": project.brand_theme,
            "checks": {
                "has_scenes": bool(project.scenes),
                "all_scenes_have_visuals": not missing_visuals,
                "all_scenes_have_audio": not missing_audio,
                "uses_no_third_party_youtube_frames": True,
                "has_source_export": bool(project.result.sources_path),
                "has_subtitles": bool(project.result.subtitles_path),
            },
            "missing_visual_scene_ids": missing_visuals,
            "missing_audio_scene_ids": missing_audio,
            "captured_source_ids": captured_sources,
            "fallback_source_ids": fallback_sources,
            "warnings": project.result.warnings,
            "manual_review_required": [
                "Проверить факты и актуальность данных.",
                "Проверить условия использования официальных сайтов/логотипов/скриншотов.",
                "Проверить необходимость AI disclosure при публикации на YouTube.",
                "Проверить, что пользователь имеет права на загруженный голос и аватар.",
            ],
        }

    def _make_tags(self, project: Project) -> list[str]:
        words = [word.strip(".,:;!?()[]{}\"'").lower() for word in project.topic.split()]
        tags = [word for word in words if len(word) >= 3][:8]
        tags.extend([project.style.value.replace("_", " "), "ai video", "youtube"])
        result: list[str] = []
        for tag in tags:
            if tag and tag not in result:
                result.append(tag)
        return result[:15]

    def _render_thumbnail(self, project: Project, path: Path) -> None:
        width, height = 1280, 720
        if project.brand_theme == "light":
            bg, card, fg, muted, accent = (245, 247, 252), (255, 255, 255), (17, 24, 39), (71, 85, 105), (79, 70, 229)
        elif project.brand_theme == "neon":
            bg, card, fg, muted, accent = (9, 12, 28), (22, 29, 55), (255, 255, 255), (190, 210, 255), (0, 229, 255)
        else:
            bg, card, fg, muted, accent = (13, 18, 32), (31, 41, 72), (255, 255, 255), (203, 213, 225), (99, 102, 241)

        image = Image.new("RGB", (width, height), bg)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle([width - 430, -80, width + 80, 360], radius=70, fill=accent)
        draw.rounded_rectangle([70, 72, 780, 648], radius=46, fill=card)
        draw.rounded_rectangle([830, 210, 1190, 520], radius=42, fill=card)
        draw.ellipse([925, 270, 1095, 440], fill=(255, 255, 255), outline=accent, width=7)
        draw.text((974, 328), "AV", font=self.font_regular, fill=(17, 24, 39))
        draw.text((875, 470), "AI AVATAR", font=self.font_small, fill=muted)

        lines = wrap_text(project.topic, width=22)[:4]
        y = 128
        for line in lines:
            draw.text((115, y), line, font=self.font_title, fill=fg)
            y += 94

        chips = [project.style.value.replace("_", " "), project.visual_mode.value.replace("_", " ")]
        if project.sources:
            chips.append(project.sources[0].name)
        x = 115
        for chip in chips[:3]:
            tw = int(draw.textlength(chip, font=self.font_small)) + 42
            draw.rounded_rectangle([x, 555, x + tw, 610], radius=20, fill=accent)
            draw.text((x + 20, 566), chip, font=self.font_small, fill=(255, 255, 255))
            x += tw + 14

        image.save(path, "PNG", optimize=True)

    def _load_font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
            "/Library/Fonts/Arial Unicode.ttf",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
        for candidate in candidates:
            if Path(candidate).exists():
                return ImageFont.truetype(candidate, size=size)
        return ImageFont.load_default()
