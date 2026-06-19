from __future__ import annotations

from datetime import datetime
from typing import Any

from app.config import ConfigurationError, Settings
from app.services.audit_log_service import AuditEvent

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - local audit mode does not need postgres extras
    psycopg = None
    dict_row = None
    Jsonb = None


class PostgresAuditRepository:
    def __init__(self, settings: Settings):
        if psycopg is None or dict_row is None or Jsonb is None:
            raise ConfigurationError("psycopg is required when AUDIT_STORAGE_BACKEND=postgres")
        if not settings.database_url:
            raise ConfigurationError("DATABASE_URL is required when AUDIT_STORAGE_BACKEND=postgres")
        self.settings = settings
        if settings.database_auto_migrate:
            self.init_schema()

    def init_schema(self) -> None:
        statements = [
            """
            create table if not exists audit_events (
                id text primary key,
                action text not null,
                actor_id text,
                resource_type text not null,
                resource_id text,
                request_id text,
                metadata jsonb not null default '{}'::jsonb,
                created_at timestamptz not null
            )
            """,
            "create index if not exists audit_events_actor_created_idx on audit_events (actor_id, created_at desc, id desc) where actor_id is not null",
            "create index if not exists audit_events_resource_created_idx on audit_events (resource_type, resource_id, created_at desc, id desc)",
            "create index if not exists audit_events_action_created_idx on audit_events (action, created_at desc, id desc)",
            "create index if not exists audit_events_created_idx on audit_events (created_at desc, id desc)",
        ]
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)

    def save(self, event: AuditEvent) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into audit_events (
                        id,
                        action,
                        actor_id,
                        resource_type,
                        resource_id,
                        request_id,
                        metadata,
                        created_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (id) do nothing
                    """,
                    (
                        event.id,
                        event.action,
                        event.actor_id,
                        event.resource_type,
                        event.resource_id,
                        event.request_id,
                        Jsonb(event.metadata),
                        event.created_at,
                    ),
                )

    def list_events(
        self,
        *,
        actor_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> list[AuditEvent]:
        filters: list[str] = []
        params: list[Any] = []
        if actor_id is not None:
            filters.append("actor_id = %s")
            params.append(actor_id)
        if resource_type is not None:
            filters.append("resource_type = %s")
            params.append(resource_type)
        if resource_id is not None:
            filters.append("resource_id = %s")
            params.append(resource_id)
        where = f"where {' and '.join(filters)}" if filters else ""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    select id, action, actor_id, resource_type, resource_id, request_id, metadata, created_at
                    from audit_events
                    {where}
                    order by created_at desc, id desc
                    """,
                    tuple(params),
                )
                rows = cursor.fetchall()
        return [self._event_from_row(row) for row in rows]

    def cleanup_old_events(self, cutoff: datetime) -> dict[str, int]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select count(*) as total from audit_events")
                total = int(cursor.fetchone()["total"])
                cursor.execute("delete from audit_events where created_at < %s returning id", (cutoff,))
                removed = len(cursor.fetchall())
        return {"removed_audit_events": removed, "skipped_audit_events": max(0, total - removed)}

    def metadata(self) -> dict[str, object]:
        return {
            "backend": "postgres",
            "database_configured": bool(self.settings.database_url),
            "auto_migrate": self.settings.database_auto_migrate,
        }

    def _event_from_row(self, row: dict[str, Any]) -> AuditEvent:
        return AuditEvent(
            id=str(row["id"]),
            action=str(row["action"]),
            actor_id=row.get("actor_id"),
            resource_type=str(row["resource_type"]),
            resource_id=row.get("resource_id"),
            request_id=row.get("request_id"),
            metadata=dict(row.get("metadata") or {}),
            created_at=row["created_at"],
        )

    def _connect(self):
        assert psycopg is not None
        assert dict_row is not None
        return psycopg.connect(
            self.settings.database_url,
            connect_timeout=self.settings.database_connect_timeout_seconds,
            row_factory=dict_row,
        )
