from __future__ import annotations

from typing import Any

from app.config import ConfigurationError, Settings
from app.models import SupportTicket, SupportTicketStatus

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - local support mode does not need postgres extras
    psycopg = None
    dict_row = None
    Jsonb = None


class PostgresSupportRepository:
    def __init__(self, settings: Settings):
        if psycopg is None or dict_row is None or Jsonb is None:
            raise ConfigurationError("psycopg is required when SUPPORT_STORAGE_BACKEND=postgres")
        if not settings.database_url:
            raise ConfigurationError("DATABASE_URL is required when SUPPORT_STORAGE_BACKEND=postgres")
        self.settings = settings
        if settings.database_auto_migrate:
            self.init_schema()

    def init_schema(self) -> None:
        statements = [
            """
            create table if not exists support_tickets (
                id text primary key,
                subject text not null,
                message text not null,
                status text not null,
                priority text not null,
                user_id text,
                organization_id text,
                project_id text,
                job_id text,
                assignee text,
                tags jsonb not null default '[]'::jsonb,
                notes jsonb not null default '[]'::jsonb,
                created_at timestamptz not null,
                updated_at timestamptz not null,
                resolved_at timestamptz
            )
            """,
            "create index if not exists support_tickets_status_updated_idx on support_tickets (status, updated_at desc, id desc)",
            "create index if not exists support_tickets_user_updated_idx on support_tickets (user_id, updated_at desc, id desc) where user_id is not null",
            "create index if not exists support_tickets_project_updated_idx on support_tickets (project_id, updated_at desc, id desc) where project_id is not null",
            "create index if not exists support_tickets_job_updated_idx on support_tickets (job_id, updated_at desc, id desc) where job_id is not null",
        ]
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)

    def save(self, ticket: SupportTicket) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into support_tickets (
                        id,
                        subject,
                        message,
                        status,
                        priority,
                        user_id,
                        organization_id,
                        project_id,
                        job_id,
                        assignee,
                        tags,
                        notes,
                        created_at,
                        updated_at,
                        resolved_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (id) do update set
                        subject = excluded.subject,
                        message = excluded.message,
                        status = excluded.status,
                        priority = excluded.priority,
                        user_id = excluded.user_id,
                        organization_id = excluded.organization_id,
                        project_id = excluded.project_id,
                        job_id = excluded.job_id,
                        assignee = excluded.assignee,
                        tags = excluded.tags,
                        notes = excluded.notes,
                        created_at = excluded.created_at,
                        updated_at = excluded.updated_at,
                        resolved_at = excluded.resolved_at
                    """,
                    (
                        ticket.id,
                        ticket.subject,
                        ticket.message,
                        ticket.status.value,
                        ticket.priority.value,
                        ticket.user_id,
                        ticket.organization_id,
                        ticket.project_id,
                        ticket.job_id,
                        ticket.assignee,
                        Jsonb(ticket.tags),
                        Jsonb([note.model_dump(mode="json") for note in ticket.notes]),
                        ticket.created_at,
                        ticket.updated_at,
                        ticket.resolved_at,
                    ),
                )

    def get_ticket(self, ticket_id: str) -> SupportTicket | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select *
                    from support_tickets
                    where id = %s
                    """,
                    (ticket_id,),
                )
                row = cursor.fetchone()
        return self._ticket_from_row(row) if row else None

    def list_tickets(
        self,
        *,
        status: SupportTicketStatus | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
    ) -> list[SupportTicket]:
        filters: list[str] = []
        params: list[Any] = []
        if status is not None:
            filters.append("status = %s")
            params.append(status.value)
        if user_id is not None:
            filters.append("user_id = %s")
            params.append(user_id)
        if project_id is not None:
            filters.append("project_id = %s")
            params.append(project_id)
        where = f"where {' and '.join(filters)}" if filters else ""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    select *
                    from support_tickets
                    {where}
                    order by updated_at desc, id desc
                    """,
                    tuple(params),
                )
                rows = cursor.fetchall()
        return [self._ticket_from_row(row) for row in rows]

    def metadata(self) -> dict[str, object]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select status, count(*) as count from support_tickets group by status")
                rows = cursor.fetchall()
        by_status = {str(row["status"]): int(row["count"]) for row in rows}
        return {
            "backend": "postgres",
            "database_configured": bool(self.settings.database_url),
            "auto_migrate": self.settings.database_auto_migrate,
            "ticket_count": sum(by_status.values()),
            "by_status": by_status,
        }

    def _ticket_from_row(self, row: dict[str, Any]) -> SupportTicket:
        return SupportTicket.model_validate(
            {
                "id": row["id"],
                "subject": row["subject"],
                "message": row["message"],
                "status": row["status"],
                "priority": row["priority"],
                "user_id": row.get("user_id"),
                "organization_id": row.get("organization_id"),
                "project_id": row.get("project_id"),
                "job_id": row.get("job_id"),
                "assignee": row.get("assignee"),
                "tags": list(row.get("tags") or []),
                "notes": list(row.get("notes") or []),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "resolved_at": row.get("resolved_at"),
            }
        )

    def _connect(self):
        assert psycopg is not None
        assert dict_row is not None
        return psycopg.connect(
            self.settings.database_url,
            connect_timeout=self.settings.database_connect_timeout_seconds,
            row_factory=dict_row,
        )
