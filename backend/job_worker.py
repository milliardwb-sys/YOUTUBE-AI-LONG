from __future__ import annotations

import argparse
import time

from app.config import get_settings
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


def build_runner() -> JobRunner:
    settings = get_settings()
    store = ProjectStore(settings)
    pipeline = VideoPipeline(
        store=store,
        compliance=ComplianceService(),
        script=ScriptService(settings),
        sources=SourceService(settings),
        visuals=VisualService(settings),
        voice=VoiceService(settings),
        avatar=AvatarService(settings),
        render=RenderService(settings),
    )
    return JobRunner(settings, pipeline, JobStore(settings))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run queued AI Video Studio jobs outside the API process.")
    parser.add_argument("--once", action="store_true", help="Run one polling pass and exit.")
    parser.add_argument("--limit", type=int, default=1, help="Maximum queued jobs to run per polling pass.")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="Seconds to wait between polling passes.")
    parser.add_argument(
        "--auto-avatar-sync",
        action="store_true",
        help="Queue sync_avatar jobs for projects with pending HeyGen avatar videos.",
    )
    args = parser.parse_args()

    runner = build_runner()
    auto_avatar_sync = args.auto_avatar_sync or runner.settings.avatar_auto_sync_enabled
    print("AI Video Studio worker started")
    try:
        while True:
            queued_avatar_jobs = []
            if auto_avatar_sync:
                queued_avatar_jobs = runner.queue_avatar_sync_candidates(limit=max(1, args.limit))
                for job in queued_avatar_jobs:
                    print(f"auto_avatar_sync job={job.id} status={job.status.value} project={job.project_id}")
            jobs = runner.run_queued_batch(limit=max(1, args.limit))
            for job in jobs:
                print(f"job={job.id} status={job.status.value} progress={job.progress} project={job.project_id}")
            if args.once:
                if not jobs and not queued_avatar_jobs:
                    print("No queued jobs")
                return 0
            if not jobs:
                time.sleep(max(0.1, args.poll_interval))
    except KeyboardInterrupt:
        print("Worker stopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
