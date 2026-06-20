from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Callable

from app.config import Settings
from app.models import JobStatus, JobType, ProjectJob, ProjectStatus
from app.pipeline import VideoPipeline
from app.postgres_job_store import PostgresJobRepository
from app.utils.files import ensure_dir, read_json, write_json
from app.utils.security import validate_job_id, validate_project_id


class JobNotFoundError(KeyError):
    pass


class JobAlreadyRunningError(RuntimeError):
    pass


class JobNotCancellableError(RuntimeError):
    pass


class JobNotRetryableError(RuntimeError):
    pass


class JobCancelledError(RuntimeError):
    pass


class JobStore:
    """Job state store with local JSON and PostgreSQL-backed modes.

    The in-process runner still executes work, but persisted job records can now live in
    PostgreSQL so status/progress survives process restarts.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.jobs_dir = ensure_dir(settings.data_dir / "_jobs")
        self._postgres: PostgresJobRepository | None = None
        if settings.job_storage_backend == "postgres":
            self._postgres = PostgresJobRepository(settings)
        self._lock = Lock()

    def job_file(self, job_id: str) -> Path:
        validate_job_id(job_id)
        return self.jobs_dir / f"{job_id}.json"

    def create(
        self,
        project_id: str,
        job_type: JobType,
        *,
        owner_id: str | None = None,
        organization_id: str | None = None,
    ) -> ProjectJob:
        validate_project_id(project_id)
        job = ProjectJob(project_id=project_id, type=job_type, owner_id=owner_id, organization_id=organization_id)
        job.add_event("queued", f"queued_{job_type.value}", 0)
        self.save(job)
        return job

    def save(self, job: ProjectJob) -> None:
        with self._lock:
            job.touch()
            if self._postgres is not None:
                self._postgres.save(job)
                return
            write_json(self.job_file(job.id), job.model_dump(mode="json"))

    def get(self, job_id: str) -> ProjectJob:
        if self._postgres is not None:
            job = self._postgres.get(job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            return job
        path = self.job_file(job_id)
        if not path.exists():
            raise JobNotFoundError(job_id)
        return ProjectJob.model_validate(read_json(path))

    def list_for_project(self, project_id: str) -> list[ProjectJob]:
        validate_project_id(project_id)
        if self._postgres is not None:
            return self._postgres.list_for_project(project_id)
        jobs: list[ProjectJob] = []
        for job_file in sorted(self.jobs_dir.glob("job_*.json")):
            job = ProjectJob.model_validate(read_json(job_file))
            if job.project_id == project_id:
                jobs.append(job)
        return sorted(jobs, key=lambda item: item.created_at, reverse=True)

    def active_for_project(self, project_id: str) -> ProjectJob | None:
        for job in self.list_for_project(project_id):
            if job.status in {JobStatus.queued, JobStatus.running}:
                return job
        return None

    def cancel(self, job_id: str, reason: str = "Job cancelled by user") -> ProjectJob:
        with self._lock:
            job = self.get(job_id)
            if job.status not in {JobStatus.queued, JobStatus.running}:
                raise JobNotCancellableError(f"Job is already {job.status}")
            job.mark_cancelled(reason)
            if self._postgres is not None:
                self._postgres.save(job)
                return job
            write_json(self.job_file(job.id), job.model_dump(mode="json"))
            return job

    def cleanup_old_jobs(self, retention_days: int | None = None) -> dict[str, int]:
        retention = retention_days if retention_days is not None else self.settings.cleanup_retention_days
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, retention))
        if self._postgres is not None:
            return self._postgres.cleanup_old_jobs(cutoff)
        removed = 0
        skipped = 0
        for job_file in sorted(self.jobs_dir.glob("job_*.json")):
            job = ProjectJob.model_validate(read_json(job_file))
            if job.status in {JobStatus.queued, JobStatus.running} or job.updated_at >= cutoff:
                skipped += 1
                continue
            job_file.unlink(missing_ok=True)
            removed += 1
        return {"removed_jobs": removed, "skipped_jobs": skipped}

    def list_all(self) -> list[ProjectJob]:
        if self._postgres is not None:
            return self._postgres.list_all()
        jobs: list[ProjectJob] = []
        for job_file in sorted(self.jobs_dir.glob("job_*.json")):
            jobs.append(ProjectJob.model_validate(read_json(job_file)))
        return sorted(jobs, key=lambda item: item.created_at, reverse=True)

    def stats(self) -> dict:
        jobs = self.list_all()
        by_status: dict[str, int] = {}
        by_type: dict[str, int] = {}
        active = 0
        terminal = 0
        for job in jobs:
            by_status[job.status.value] = by_status.get(job.status.value, 0) + 1
            by_type[job.type.value] = by_type.get(job.type.value, 0) + 1
            if job.status in {JobStatus.queued, JobStatus.running}:
                active += 1
            else:
                terminal += 1
        return {
            "storage_backend": self.settings.job_storage_backend,
            "job_count": len(jobs),
            "active_jobs": active,
            "terminal_jobs": terminal,
            "jobs_by_status": by_status,
            "jobs_by_type": by_type,
        }

    def metadata(self) -> dict[str, object]:
        if self._postgres is not None:
            return self._postgres.metadata()
        return {
            "backend": "local",
            "jobs_dir": self.jobs_dir.as_posix(),
        }

    def health(self) -> bool:
        if self._postgres is not None:
            return self._postgres.ping()
        return self.jobs_dir.exists()


class JobRunner:
    def __init__(self, settings: Settings, pipeline: VideoPipeline, job_store: JobStore):
        self.settings = settings
        self.pipeline = pipeline
        self.job_store = job_store
        self.executor = ThreadPoolExecutor(max_workers=max(1, settings.job_workers))
        self._start_lock = Lock()

    def start(self, project_id: str, job_type: JobType, *, owner_id: str | None = None) -> ProjectJob:
        validate_project_id(project_id)
        with self._start_lock:
            active = self.job_store.active_for_project(project_id)
            if active is not None:
                return active

            project = self.pipeline.store.get(project_id)
            job = self.job_store.create(
                project_id,
                job_type,
                owner_id=owner_id or project.owner_id,
                organization_id=project.organization_id,
            )
            project.status = ProjectStatus.queued
            project.touch(f"queued_{job_type.value}")
            self.pipeline.store.save(project)

        if self.settings.run_jobs_inline:
            self._execute(job.id)
        elif self.settings.execute_jobs_in_api:
            self.executor.submit(self._execute, job.id)
        else:
            job.add_event("queued_for_external_worker", "Waiting for external job worker", job.progress)
            self.job_store.save(job)
        return self.job_store.get(job.id)

    def run_next_queued(self) -> ProjectJob | None:
        queued = [job for job in self.job_store.list_all() if job.status == JobStatus.queued]
        if not queued:
            return None
        job = sorted(queued, key=lambda item: (item.created_at, item.id))[0]
        self._execute(job.id)
        return self.job_store.get(job.id)

    def run_queued_batch(self, *, limit: int = 1) -> list[ProjectJob]:
        completed: list[ProjectJob] = []
        for _ in range(max(1, limit)):
            job = self.run_next_queued()
            if job is None:
                break
            completed.append(job)
        return completed

    def cancel(self, job_id: str) -> ProjectJob:
        job = self.job_store.cancel(job_id)
        try:
            project = self.pipeline.store.get(job.project_id)
            if project.status in {ProjectStatus.queued, ProjectStatus.researching, ProjectStatus.rendering}:
                project.status = ProjectStatus.cancelled
                project.error = job.error
                project.touch("job_cancelled")
                self.pipeline.store.save(project)
        except Exception:
            pass
        return job

    def retry(self, job_id: str) -> ProjectJob:
        original = self.job_store.get(job_id)
        if original.status in {JobStatus.queued, JobStatus.running}:
            raise JobNotRetryableError("Active jobs cannot be retried")
        retried = self.start(original.project_id, original.type, owner_id=original.owner_id)
        retried.add_event("retry_of", original.id, retried.progress)
        self.job_store.save(retried)
        return retried

    def _execute(self, job_id: str) -> None:
        job = self.job_store.get(job_id)
        try:
            self._raise_if_cancelled(job.id)
            job.mark_running(f"running_{job.type.value}")
            job.progress = 5
            self.job_store.save(job)
            self._raise_if_cancelled(job.id)

            if job.type == JobType.generate_all:
                self._run_generate_all(job)
            else:
                self._run_single(job)

            self._raise_if_cancelled(job.id)
            project = self.pipeline.store.get(job.project_id)
            job = self.job_store.get(job_id)
            if project.status == ProjectStatus.failed:
                job.mark_failed(project.error or "Project failed")
            else:
                job.mark_completed(project.status)
            self.job_store.save(job)
        except JobCancelledError as exc:
            job = self.job_store.get(job_id)
            if job.status != JobStatus.cancelled:
                job.mark_cancelled(str(exc))
                self.job_store.save(job)
            try:
                project = self.pipeline.store.get(job.project_id)
                project.status = ProjectStatus.cancelled
                project.error = job.error
                project.touch("job_cancelled")
                self.pipeline.store.save(project)
            except Exception:
                pass
        except Exception as exc:  # noqa: BLE001 - job must always finish with saved error
            job = self.job_store.get(job_id)
            if job.status == JobStatus.cancelled:
                return
            job.mark_failed(str(exc))
            self.job_store.save(job)
            try:
                project = self.pipeline.store.get(job.project_id)
                project.status = ProjectStatus.failed
                project.error = str(exc)
                project.touch("job_failed")
                self.pipeline.store.save(project)
            except Exception:
                pass

    def _run_single(self, job: ProjectJob) -> None:
        steps: dict[JobType, tuple[str, int, Callable[[str], object]]] = {
            JobType.generate_script: ("generate_script", 90, self.pipeline.generate_script),
            JobType.collect_sources: ("collect_sources", 90, self.pipeline.collect_sources),
            JobType.generate_slides: ("generate_slides", 90, self.pipeline.generate_slides),
            JobType.generate_voice: ("generate_voice", 90, self.pipeline.generate_voice),
            JobType.prepare_avatar: ("prepare_avatar", 90, self.pipeline.prepare_avatar),
            JobType.sync_avatar: ("sync_avatar", 90, self.pipeline.sync_avatar),
            JobType.render: ("render", 90, self.pipeline.render),
        }
        step = steps.get(job.type)
        if step is None:
            raise RuntimeError(f"Unsupported job type: {job.type}")
        name, progress, fn = step
        self._update(job, progress=25, step=f"starting_{name}")
        self._raise_if_cancelled(job.id)
        fn(job.project_id)
        self._raise_if_cancelled(job.id)
        self._update(job, progress=progress, step=f"finished_{name}")

    def _run_generate_all(self, job: ProjectJob) -> None:
        workflow: list[tuple[str, int, Callable[[str], object]]] = [
            ("generate_script", 15, self.pipeline.generate_script),
            ("collect_sources", 30, self.pipeline.collect_sources),
            ("generate_voice", 48, self.pipeline.generate_voice),
            ("generate_slides", 66, self.pipeline.generate_slides),
            ("prepare_avatar", 78, self.pipeline.prepare_avatar),
            ("sync_avatar", 84, self.pipeline.sync_avatar),
            ("render", 95, self.pipeline.render),
        ]
        for name, progress, fn in workflow:
            self._update(job, progress=max(1, progress - 8), step=f"starting_{name}")
            self._raise_if_cancelled(job.id)
            project = fn(job.project_id)
            self._raise_if_cancelled(job.id)
            self._update(job, progress=progress, step=f"finished_{name}")
            if project.status == ProjectStatus.failed:
                raise RuntimeError(project.error or f"Project failed at {name}")

    def _update(self, job: ProjectJob, *, progress: int, step: str) -> None:
        fresh = self.job_store.get(job.id)
        if fresh.status == JobStatus.cancelled:
            raise JobCancelledError(fresh.error or "Job cancelled")
        fresh.progress = max(fresh.progress, min(99, progress))
        fresh.current_step = step
        fresh.add_event("progress", step, fresh.progress)
        self.job_store.save(fresh)
        job.progress = fresh.progress
        job.current_step = fresh.current_step

    def _raise_if_cancelled(self, job_id: str) -> None:
        fresh = self.job_store.get(job_id)
        if fresh.status == JobStatus.cancelled:
            raise JobCancelledError(fresh.error or "Job cancelled")
