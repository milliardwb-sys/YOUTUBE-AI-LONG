from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.config import Settings
from app.utils.files import ensure_dir, read_json, write_json

IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


class InvalidIdempotencyKeyError(ValueError):
    pass


class IdempotencyConflictError(ValueError):
    pass


@dataclass(frozen=True)
class IdempotencyRecord:
    key_hash: str
    scope: str
    request_hash: str
    resource_type: str
    resource_id: str
    created_at: datetime


class IdempotencyStore:
    """Idempotency records for retry-safe API writes."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.records_dir = ensure_dir(settings.data_dir / "_idempotency")
        self._postgres = None
        if settings.idempotency_storage_backend == "postgres":
            from app.postgres_idempotency_store import PostgresIdempotencyRepository

            self._postgres = PostgresIdempotencyRepository(settings)

    def normalize_key(self, value: str) -> str:
        key = value.strip()
        if not IDEMPOTENCY_KEY_RE.fullmatch(key):
            raise InvalidIdempotencyKeyError(
                "Idempotency-Key must be 8-128 chars and use letters, digits, '.', '_', ':' or '-'"
            )
        return key

    def request_hash(self, payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def get(self, *, key: str, scope: str, request_hash: str) -> IdempotencyRecord | None:
        key_hash = self._key_hash(scope, key)
        if self._postgres is not None:
            record = self._postgres.get(key_hash)
            if record is None:
                return None
            if record.request_hash != request_hash:
                raise IdempotencyConflictError("Idempotency-Key was already used for a different request")
            return record
        path = self._record_file(scope, key)
        if not path.exists():
            return None
        record = self._record_from_json(read_json(path))
        if record.request_hash != request_hash:
            raise IdempotencyConflictError("Idempotency-Key was already used for a different request")
        return record

    def save(
        self,
        *,
        key: str,
        scope: str,
        request_hash: str,
        resource_type: str,
        resource_id: str,
    ) -> IdempotencyRecord:
        record = IdempotencyRecord(
            key_hash=self._key_hash(scope, key),
            scope=scope,
            request_hash=request_hash,
            resource_type=resource_type,
            resource_id=resource_id,
            created_at=datetime.now(timezone.utc),
        )
        if self._postgres is not None:
            self._postgres.save(record)
            return record
        write_json(self._record_file(scope, key), self._record_to_json(record))
        return record

    def delete(self, *, key: str, scope: str) -> None:
        if self._postgres is not None:
            self._postgres.delete(self._key_hash(scope, key))
            return
        self._record_file(scope, key).unlink(missing_ok=True)

    def save_record(self, record: IdempotencyRecord) -> IdempotencyRecord:
        if self._postgres is not None:
            self._postgres.save(record)
            return record
        write_json(self.records_dir / f"{record.key_hash}.json", self._record_to_json(record))
        return record

    def list_records(self) -> list[IdempotencyRecord]:
        if self._postgres is not None:
            return self._postgres.list_records()
        records: list[IdempotencyRecord] = []
        for record_file in sorted(self.records_dir.glob("*.json")):
            try:
                records.append(self._record_from_json(read_json(record_file)))
            except (OSError, ValueError, TypeError, KeyError):
                continue
        return sorted(records, key=lambda item: (item.created_at, item.key_hash), reverse=True)

    def cleanup_old_records(self, retention_days: int | None = None) -> dict[str, int]:
        retention = retention_days if retention_days is not None else self.settings.cleanup_retention_days
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, retention))
        if self._postgres is not None:
            return self._postgres.cleanup_old_records(cutoff)
        removed = 0
        skipped = 0
        for record_file in sorted(self.records_dir.glob("*.json")):
            try:
                record = self._record_from_json(read_json(record_file))
            except (OSError, ValueError, TypeError):
                skipped += 1
                continue
            if record.created_at >= cutoff:
                skipped += 1
                continue
            record_file.unlink(missing_ok=True)
            removed += 1
        return {"removed_idempotency_records": removed, "skipped_idempotency_records": skipped}

    def metadata(self) -> dict[str, object]:
        if self._postgres is not None:
            return self._postgres.metadata()
        return {
            "backend": "local",
            "records_dir": self.records_dir.as_posix(),
            "record_count": len(list(self.records_dir.glob("*.json"))),
        }

    def _record_file(self, scope: str, key: str) -> Path:
        return self.records_dir / f"{self._key_hash(scope, key)}.json"

    def _key_hash(self, scope: str, key: str) -> str:
        return hashlib.sha256(f"{scope}:{key}".encode("utf-8")).hexdigest()

    def _record_to_json(self, record: IdempotencyRecord) -> dict[str, str]:
        return {
            "key_hash": record.key_hash,
            "scope": record.scope,
            "request_hash": record.request_hash,
            "resource_type": record.resource_type,
            "resource_id": record.resource_id,
            "created_at": record.created_at.isoformat(),
        }

    def _record_from_json(self, payload: dict[str, Any]) -> IdempotencyRecord:
        created_at = datetime.fromisoformat(str(payload["created_at"]))
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return IdempotencyRecord(
            key_hash=str(payload["key_hash"]),
            scope=str(payload["scope"]),
            request_hash=str(payload["request_hash"]),
            resource_type=str(payload["resource_type"]),
            resource_id=str(payload["resource_id"]),
            created_at=created_at,
        )
