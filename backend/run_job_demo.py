from __future__ import annotations

from app.config import get_settings
from app.models import BrandTheme, JobType, ProjectCreate, VideoStyle, VisualMode, VoiceProviderName
from app.pipeline import VideoPipeline
from app.services.avatar_service import AvatarService
from app.services.compliance_service import ComplianceService
from app.services.job_service import JobRunner, JobStore
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
    pipeline = build_pipeline(store)
    jobs = JobStore(settings)
    runner = JobRunner(settings, pipeline, jobs)

    project = store.create_project(
        ProjectCreate(
            topic="AI-аватар показывает 5 сервисов для создания YouTube-видео в 2026 году",
            duration_minutes=2,
            style=VideoStyle.ai_news_avatar,
            language="ru",
            audience="создатели YouTube-каналов",
            visual_mode=VisualMode.official_sites_plus_ai,
            source_urls=["https://www.heygen.com/", "https://runwayml.com/", "https://www.synthesia.io/"],
            voice_provider=VoiceProviderName.placeholder,
            brand_theme=BrandTheme.neon,
            avatar_enabled=True,
            avatar_position="bottom_left",
            burn_subtitles=True,
        )
    )

    job = runner.start(project.id, JobType.generate_all)
    job = jobs.get(job.id)
    project = store.get(project.id)

    print("Project:", project.id)
    print("Job:", job.id)
    print("Job status:", job.status)
    print("Job progress:", job.progress)
    print("Project status:", project.status)
    print("Video:", project.result.final_video_path)
    print("Package:", project.result.export_package_path)
    if job.error:
        print("Job error:", job.error)
    if project.error:
        print("Project error:", project.error)


if __name__ == "__main__":
    main()
