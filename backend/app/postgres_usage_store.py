from __future__ import annotations

from datetime import datetime
from typing import Any

from app.config import ConfigurationError, Settings
from app.services.usage_service import UsageEvent

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - local usage mode does not need postgres extras
    psycopg = None
    dict_row = None
    Jsonb = None


class PostgresUsageRepository:
    def __init__(self, settings: Settings):
        if psycopg is None or dict_row is None or Jsonb is None:
            raise ConfigurationError("psycopg is required when USAGE_STORAGE_BACKEND=postgres")
        if not settings.database_url:
            raise ConfigurationError("DATABASE_URL is required when USAGE_STORAGE_BACKEND=postgres")
        self.settings = settings
        if settings.database_auto_migrate:
            self.init_schema()

    def init_schema(self) -> None:
        statements = [
            """
            create table if not exists usage_events (
                id text primary key,
                action text not null,
                actor_id text,
                resource_type text not null,
                resource_id text,
                units integer not null default 0,
                estimated_cost_cents integer not null default 0,
                metadata jsonb not null default '{}'::jsonb,
                created_at timestamptz not null
            )
            """,
            "create index if not exists usage_events_actor_created_idx on usage_events (actor_id, created_at desc, id desc) where actor_id is not null",
            "create index if not exists usage_events_action_created_idx on usage_events (action, created_at desc, id desc)",
            "create index if not exists usage_events_resource_created_idx on usage_events (resource_type, resource_id, created_at desc, id desc)",
            "create index if not exists usage_events_created_idx on usage_events (created_at desc, id desc)",
        ]
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)

    def save(self, event: UsageEvent) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into usage_events (
                        id,
                        action,
                        actor_id,
                        resource_type,
                        resource_id,
                        units,
                        estimated_cost_cents,
                        metadata,
                        created_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (id) do nothing
                    """,
                    (
                        event.id,
                        event.action,
                        event.actor_id,
                        event.resource_type,
                        event.resource_id,
                        event.units,
                        event.estimated_cost_cents,
                        Jsonb(event.metadata),
                        event.created_at,
                    ),
                )

    def list_events(self, *, actor_id: str | None = None) -> list[UsageEvent]:
        filters: list[str] = []
        params: list[Any] = []
        if actor_id is not None:
            filters.append("actor_id = %s")
            params.append(actor_id)
        where = f"where {' and '.join(filters)}" if filters else ""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    select id, action, actor_id, resource_type, resource_id, units, estimated_cost_cents, metadata, created_at
                    from usage_events
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
                cursor.execute("select count(*) as total from usage_events")
                total = int(cursor.fetchone()["total"])
                cursor.execute("delete from usage_events where created_at < %s returning id", (cutoff,))
                removed = len(cursor.fetchall())
        return {"removed_usage_events": removed, "skipped_usage_events": max(0, total - removed)}

    def metadata(self) -> dict[str, object]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select count(*) as total, coalesce(sum(units), 0) as units, coalesce(sum(estimated_cost_cents), 0) as cost from usage_events")
                row = cursor.fetchone()
        return {
            "backend": "postgres",
            "database_configured": bool(self.settings.database_url),
            "auto_migrate": self.settings.database_auto_migrate,
            "event_count": int(row["total"]),
            "total_units": int(row["units"]),
            "estimated_cost_cents": int(row["cost"]),
        }

    def _event_from_row(self, row: dict[str, Any]) -> UsageEvent:
        return UsageEvent(
            id=str(row["id"]),
            action=str(row["action"]),
            actor_id=row.get("actor_id"),
            resource_type=str(row["resource_type"]),
            resource_id=row.get("resource_id"),
            units=int(row.get("units") or 0),
            estimated_cost_cents=int(row.get("estimated_cost_cents") or 0),
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
