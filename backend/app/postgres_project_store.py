from __future__ import annotations

from typing import Any

from app.config import ConfigurationError, Settings
from app.models import Project

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - exercised only in envs without postgres extras
    psycopg = None
    dict_row = None
    Jsonb = None


class PostgresProjectRepository:
    """PostgreSQL-backed project repository.

    Project payloads stay as version-tolerant jsonb documents while API query fields
    are duplicated into indexed columns. This keeps the MVP model flexible without
    forcing every scene/source/result field into relational tables at once.
    """

    def __init__(self, settings: Settings):
        if psycopg is None or dict_row is None or Jsonb is None:
            raise ConfigurationError("psycopg is required when PROJECT_STORAGE_BACKEND=postgres")
        if not settings.database_url:
            raise ConfigurationError("DATABASE_URL is required when PROJECT_STORAGE_BACKEND=postgres")
        self.settings = settings
        if settings.database_auto_migrate:
            self.init_schema()

    def init_schema(self) -> None:
        statements = [
            """
            create table if not exists projects (
                id text primary key,
                owner_id text,
                organization_id text,
                status text not null,
                current_step text not null,
                topic text not null,
                created_at timestamptz not null,
                updated_at timestamptz not null,
                payload jsonb not null
            )
            """,
            "create index if not exists projects_owner_created_idx on projects (owner_id, created_at desc, id desc) where owner_id is not null",
            "create index if not exists projects_organization_created_idx on projects (organization_id, created_at desc, id desc) where organization_id is not null",
            "create index if not exists projects_status_created_idx on projects (status, created_at desc, id desc)",
            "create index if not exists projects_created_idx on projects (created_at desc, id desc)",
            """
            create index if not exists projects_active_idx
            on projects (updated_at desc, id desc)
            where status in ('queued', 'researching', 'rendering')
            """,
        ]
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)

    def save(self, project: Project) -> None:
        payload = project.model_dump(mode="json")
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into projects (
                        id,
                        owner_id,
                        organization_id,
                        status,
                        current_step,
                        topic,
                        created_at,
                        updated_at,
                        payload
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (id) do update set
                        owner_id = excluded.owner_id,
                        organization_id = excluded.organization_id,
                        status = excluded.status,
                        current_step = excluded.current_step,
                        topic = excluded.topic,
                        created_at = excluded.created_at,
                        updated_at = excluded.updated_at,
                        payload = excluded.payload
                    """,
                    (
                        project.id,
                        project.owner_id,
                        project.organization_id,
                        project.status.value,
                        project.current_step,
                        project.topic,
                        project.created_at,
                        project.updated_at,
                        Jsonb(payload),
                    ),
                )

    def get(self, project_id: str) -> Project | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select payload from projects where id = %s", (project_id,))
                row = cursor.fetchone()
        if row is None:
            return None
        return Project.model_validate(row["payload"])

    def list_projects(self, *, owner_id: str | None = None) -> list[Project]:
        if owner_id is None:
            query = "select payload from projects order by created_at desc, id desc"
            params: tuple[Any, ...] = ()
        else:
            query = "select payload from projects where owner_id = %s order by created_at desc, id desc"
            params = (owner_id,)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
        return [Project.model_validate(row["payload"]) for row in rows]

    def delete(self, project_id: str) -> bool:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("delete from projects where id = %s returning id", (project_id,))
                return cursor.fetchone() is not None

    def ping(self) -> bool:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("select to_regclass('public.projects') is not null as ready")
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
