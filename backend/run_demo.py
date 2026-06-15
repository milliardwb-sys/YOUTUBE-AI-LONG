from __future__ import annotations

from app.config import get_settings
from app.models import BrandTheme, ProjectCreate, ScriptProviderName, VideoStyle, VisualMode, VoiceProviderName
from app.pipeline import VideoPipeline
from app.services.avatar_service import AvatarService
from app.services.compliance_service import ComplianceService
from app.services.render_service import RenderService
from app.services.script_service import ScriptService
from app.services.source_service import SourceService
from app.services.visual_service import VisualService
from app.services.voice_service import VoiceService
from app.storage import ProjectStore


def build_pipeline(store: ProjectStore) -> VideoPipeline:
    settings = store.settings
    return VideoPipeline(
        store=store,
        compliance=ComplianceService(),
        script=ScriptService(settings),
        sources=SourceService(settings),
        visuals=VisualService(settings),
        voice=VoiceService(settings),
        avatar=AvatarService(),
        render=RenderService(settings),
    )


def main() -> None:
    settings = get_settings()
    store = ProjectStore(settings)
    project = store.create_project(
        ProjectCreate(
            topic="5 AI-сервисов для создания видео в 2026 году",
            duration_minutes=1,
            style=VideoStyle.expert_review,
            language="ru",
            audience="создатели YouTube-каналов",
            visual_mode=VisualMode.official_sites_plus_ai,
            source_urls=["https://www.heygen.com/", "https://runwayml.com/"],
            script_provider=ScriptProviderName.template,
            voice_provider=VoiceProviderName.placeholder,
            brand_theme=BrandTheme.neon,
            avatar_enabled=True,
            avatar_position="bottom_right",
            burn_subtitles=False,
        )
    )
    pipeline = build_pipeline(store)
    project = pipeline.generate_all(project.id)
    print("Project:", project.id)
    print("Status:", project.status)
    print("Sources:", len(project.sources))
    print("Video:", project.result.final_video_path)
    print("Subtitles:", project.result.subtitles_path)
    print("Description:", project.result.description_path)
    print("Storyboard:", project.result.storyboard_path)
    print("Thumbnail:", project.result.thumbnail_path)
    print("Quality report:", project.result.quality_report_path)
    print("Package:", project.result.export_package_path)
    if project.error:
        print("Error:", project.error)
    if project.result.warnings:
        print("Warnings:")
        for warning in project.result.warnings:
            print("-", warning)


if __name__ == "__main__":
    main()
