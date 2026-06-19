from __future__ import annotations

from datetime import datetime
from typing import Any

from app.config import ConfigurationError, Settings
from app.services.idempotency_service import IdempotencyRecord

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - local idempotency mode does not need postgres extras
    psycopg = None
    dict_row = None


class PostgresIdempotencyRepository:
    def __init__(self, settings: Settings):
        if psycopg is None or dict_row is None:
            raise ConfigurationError("psycopg is required when IDEMPOTENCY_STORAGE_BACKEND=postgres")
        if not settings.database_url:
            raise ConfigurationError("DATABASE_URL is required when IDEMPOTENCY_STORAGE_BACKEND=postgres")
        self.settings = settings
        if settings.database_auto_migrate:
            self.init_schema()

    def init_schema(self) -> None:
        statements = [
            """
            create table if not exists idempotency_records (
                key_hash text primary key,
                scope text not null,
                request_hash text not null,
                resource_type text not null,
                resource_id text not null,
                created_at timestamptz not null
            )
            """,
            "create index if not exists idempotency_records_scope_created_idx on idempotency_records (scope, created_at desc)",
            "create index if not exists idempotency_records_created_idx on idempotency_records (created_at desc)",
        ]
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)

    def get(self, key_hash: str) -> IdempotencyRecord | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select key_hash, scope, request_hash, resource_type, resource_id, created_at
                    from idempotency_records
                    where key_hash = %s
                    """,
                    (key_hash,),
                )
                row = cursor.fetchone()
        return self._record_from_row(row) if row else None

    def save(self, record: IdempotencyRecord) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into idempotency_records (
                        key_hash,
                        scope,
                        request_hash,
                        resource_type,
                        resource_id,
                        created_at
                    )
                    values (%s, %s, %s, %s, %s, %s)
                    on conflict (key_hash) do nothing
                    """,
                    (
                        record.key_hash,
                        record.scope,
                        record.request_hash,
                        record.resource_type,
                        record.resource_id,
                        record.created_at,
                    ),
                )

    def list_records(self) -> list[IdempotencyRecord]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select key_hash, scope, request_hash, resource_type, resource_id, created_at
                    from idempotency_records
                    order by created_at desc, key_hash desc
                    """
                )
                rows = cursor.fetchall()
        return [self._record_from_row(row) for row in rows]

    def delete(self, key_hash: str) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("delete from idempotency_records where key_hash = %s", (key_hash,))

    def cleanup_old_records(self, cutoff: datetime) -> dict[str, int]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select count(*) as total from idempotency_records")
                total = int(cursor.fetchone()["total"])
                cursor.execute("delete from idempotency_records where created_at < %s returning key_hash", (cutoff,))
                removed = len(cursor.fetchall())
        return {"removed_idempotency_records": removed, "skipped_idempotency_records": max(0, total - removed)}

    def metadata(self) -> dict[str, object]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select count(*) as total from idempotency_records")
                total = int(cursor.fetchone()["total"])
        return {
            "backend": "postgres",
            "database_configured": bool(self.settings.database_url),
            "auto_migrate": self.settings.database_auto_migrate,
            "record_count": total,
        }

    def _record_from_row(self, row: dict[str, Any]) -> IdempotencyRecord:
        return IdempotencyRecord(
            key_hash=str(row["key_hash"]),
            scope=str(row["scope"]),
            request_hash=str(row["request_hash"]),
            resource_type=str(row["resource_type"]),
            resource_id=str(row["resource_id"]),
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
