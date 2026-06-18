from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import Settings
from app.utils.files import ensure_dir, read_json, write_json


@dataclass(frozen=True)
class AuditEvent:
    id: str
    action: str
    actor_id: str | None
    resource_type: str
    resource_id: str | None
    request_id: str | None
    metadata: dict[str, Any]
    created_at: datetime


class AuditLogService:
    """Append-only local audit log for MVP user and project actions."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.events_dir = ensure_dir(settings.data_dir / "_audit")

    def record(
        self,
        action: str,
        *,
        actor_id: str | None = None,
        resource_type: str = "system",
        resource_id: str | None = None,
        request_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            id=f"audit_{uuid4().hex[:16]}",
            action=action,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=request_id,
            metadata=metadata or {},
            created_at=datetime.now(timezone.utc),
        )
        write_json(self._event_file(event), self._event_to_json(event))
        return event

    def list_events(
        self,
        *,
        actor_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> list[AuditEvent]:
        events: list[AuditEvent] = []
        for event_file in sorted(self.events_dir.glob("audit_*.json")):
            try:
                event = self._event_from_json(read_json(event_file))
            except (OSError, ValueError, TypeError, KeyError):
                continue
            if actor_id is not None and event.actor_id != actor_id:
                continue
            if resource_type is not None and event.resource_type != resource_type:
                continue
            if resource_id is not None and event.resource_id != resource_id:
                continue
            events.append(event)
        return sorted(events, key=lambda item: (item.created_at, item.id), reverse=True)

    def cleanup_old_events(self, retention_days: int | None = None) -> dict[str, int]:
        retention = retention_days if retention_days is not None else self.settings.cleanup_retention_days
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, retention))
        removed = 0
        skipped = 0
        for event_file in sorted(self.events_dir.glob("audit_*.json")):
            try:
                event = self._event_from_json(read_json(event_file))
            except (OSError, ValueError, TypeError, KeyError):
                skipped += 1
                continue
            if event.created_at >= cutoff:
                skipped += 1
                continue
            event_file.unlink(missing_ok=True)
            removed += 1
        return {"removed_audit_events": removed, "skipped_audit_events": skipped}

    def _event_file(self, event: AuditEvent) -> Path:
        return self.events_dir / f"{event.id}.json"

    def _event_to_json(self, event: AuditEvent) -> dict[str, Any]:
        return {
            "id": event.id,
            "action": event.action,
            "actor_id": event.actor_id,
            "resource_type": event.resource_type,
            "resource_id": event.resource_id,
            "request_id": event.request_id,
            "metadata": event.metadata,
            "created_at": event.created_at.isoformat(),
        }

    def _event_from_json(self, payload: dict[str, Any]) -> AuditEvent:
        created_at = datetime.fromisoformat(str(payload["created_at"]))
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return AuditEvent(
            id=str(payload["id"]),
            action=str(payload["action"]),
            actor_id=payload.get("actor_id"),
            resource_type=str(payload["resource_type"]),
            resource_id=payload.get("resource_id"),
            request_id=payload.get("request_id"),
            metadata=dict(payload.get("metadata") or {}),
            created_at=created_at,
        )
