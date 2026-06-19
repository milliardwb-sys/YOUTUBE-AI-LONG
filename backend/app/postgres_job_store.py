from __future__ import annotations

from datetime import datetime

from app.config import ConfigurationError, Settings
from app.models import ProjectJob

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - exercised only in envs without postgres extras
    psycopg = None
    dict_row = None
    Jsonb = None


class PostgresJobRepository:
    """PostgreSQL-backed durable job state repository."""

    def __init__(self, settings: Settings):
        if psycopg is None or dict_row is None or Jsonb is None:
            raise ConfigurationError("psycopg is required when JOB_STORAGE_BACKEND=postgres")
        if not settings.database_url:
            raise ConfigurationError("DATABASE_URL is required when JOB_STORAGE_BACKEND=postgres")
        self.settings = settings
        if settings.database_auto_migrate:
            self.init_schema()

    def init_schema(self) -> None:
        statements = [
            """
            create table if not exists jobs (
                id text primary key,
                project_id text not null,
                owner_id text,
                organization_id text,
                type text not null,
                status text not null,
                progress integer not null,
                current_step text not null,
                created_at timestamptz not null,
                updated_at timestamptz not null,
                started_at timestamptz,
                completed_at timestamptz,
                payload jsonb not null
            )
            """,
            "create index if not exists jobs_project_created_idx on jobs (project_id, created_at desc, id desc)",
            "create index if not exists jobs_status_updated_idx on jobs (status, updated_at desc, id desc)",
            "create index if not exists jobs_owner_created_idx on jobs (owner_id, created_at desc, id desc) where owner_id is not null",
            "create index if not exists jobs_organization_created_idx on jobs (organization_id, created_at desc, id desc) where organization_id is not null",
            """
            create index if not exists jobs_active_idx
            on jobs (updated_at desc, id desc)
            where status in ('queued', 'running')
            """,
        ]
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)

    def save(self, job: ProjectJob) -> None:
        payload = job.model_dump(mode="json")
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into jobs (
                        id,
                        project_id,
                        owner_id,
                        organization_id,
                        type,
                        status,
                        progress,
                        current_step,
                        created_at,
                        updated_at,
                        started_at,
                        completed_at,
                        payload
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (id) do update set
                        project_id = excluded.project_id,
                        owner_id = excluded.owner_id,
                        organization_id = excluded.organization_id,
                        type = excluded.type,
                        status = excluded.status,
                        progress = excluded.progress,
                        current_step = excluded.current_step,
                        created_at = excluded.created_at,
                        updated_at = excluded.updated_at,
                        started_at = excluded.started_at,
                        completed_at = excluded.completed_at,
                        payload = excluded.payload
                    """,
                    (
                        job.id,
                        job.project_id,
                        job.owner_id,
                        job.organization_id,
                        job.type.value,
                        job.status.value,
                        job.progress,
                        job.current_step,
                        job.created_at,
                        job.updated_at,
                        job.started_at,
                        job.completed_at,
                        Jsonb(payload),
                    ),
                )

    def get(self, job_id: str) -> ProjectJob | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select payload from jobs where id = %s", (job_id,))
                row = cursor.fetchone()
        if row is None:
            return None
        return ProjectJob.model_validate(row["payload"])

    def list_for_project(self, project_id: str) -> list[ProjectJob]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "select payload from jobs where project_id = %s order by created_at desc, id desc",
                    (project_id,),
                )
                rows = cursor.fetchall()
        return [ProjectJob.model_validate(row["payload"]) for row in rows]

    def list_all(self) -> list[ProjectJob]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select payload from jobs order by created_at desc, id desc")
                rows = cursor.fetchall()
        return [ProjectJob.model_validate(row["payload"]) for row in rows]

    def cleanup_old_jobs(self, cutoff: datetime) -> dict[str, int]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select count(*) as total from jobs")
                total = int(cursor.fetchone()["total"])
                cursor.execute(
                    """
                    delete from jobs
                    where status not in ('queued', 'running')
                      and updated_at < %s
                    returning id
                    """,
                    (cutoff,),
                )
                removed = len(cursor.fetchall())
        return {"removed_jobs": removed, "skipped_jobs": max(0, total - removed)}

    def ping(self) -> bool:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("select to_regclass('public.jobs') is not null as ready")
                    row = cursor.fetchone()
                    return bool(row and row["ready"])
        except Exception:
            return False

    def metadata(self) -> dict[str, object]:
        return {
            "backend": "postgres",
            "database_configured": bool(self.settings.database_url),
            "auto_migrate": self.settings.database_auto_migrate,
        }

    def _connect(self):
        assert psycopg is not None
        assert dict_row is not None
        return psycopg.connect(
            self.settings.database_url,
            connect_timeout=self.settings.database_connect_timeout_seconds,
            row_factory=dict_row,
        )
