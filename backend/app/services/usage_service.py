from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import Settings
from app.utils.files import ensure_dir, read_json, write_json


@dataclass(frozen=True)
class UsageEvent:
    id: str
    action: str
    actor_id: str | None
    resource_type: str
    resource_id: str | None
    units: int
    estimated_cost_cents: int
    metadata: dict[str, Any]
    created_at: datetime


class UsageService:
    """Usage and cost ledger for quota/billing foundations."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.events_dir = ensure_dir(settings.data_dir / "_usage")
        self._postgres = None
        if settings.usage_storage_backend == "postgres":
            from app.postgres_usage_store import PostgresUsageRepository

            self._postgres = PostgresUsageRepository(settings)

    def record(
        self,
        action: str,
        *,
        actor_id: str | None = None,
        resource_type: str = "system",
        resource_id: str | None = None,
        units: int = 1,
        estimated_cost_cents: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> UsageEvent:
        event = UsageEvent(
            id=f"usage_{uuid4().hex[:16]}",
            action=action,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            units=max(0, units),
            estimated_cost_cents=max(0, estimated_cost_cents),
            metadata=metadata or {},
            created_at=datetime.now(timezone.utc),
        )
        self.save_event(event)
        return event

    def save_event(self, event: UsageEvent) -> UsageEvent:
        if self._postgres is not None:
            self._postgres.save(event)
            return event
        write_json(self._event_file(event), self._event_to_json(event))
        return event

    def list_events(self, *, actor_id: str | None = None) -> list[UsageEvent]:
        if self._postgres is not None:
            return self._postgres.list_events(actor_id=actor_id)
        events: list[UsageEvent] = []
        for event_file in sorted(self.events_dir.glob("usage_*.json")):
            try:
                event = self._event_from_json(read_json(event_file))
            except (OSError, ValueError, TypeError, KeyError):
                continue
            if actor_id is not None and event.actor_id != actor_id:
                continue
            events.append(event)
        return sorted(events, key=lambda item: (item.created_at, item.id), reverse=True)

    def summary(self, *, actor_id: str | None = None) -> dict[str, Any]:
        events = self.list_events(actor_id=actor_id)
        by_action: dict[str, int] = {}
        total_units = 0
        total_cost = 0
        for event in events:
            by_action[event.action] = by_action.get(event.action, 0) + 1
            total_units += event.units
            total_cost += event.estimated_cost_cents
        return {
            "event_count": len(events),
            "total_units": total_units,
            "estimated_cost_cents": total_cost,
            "events_by_action": by_action,
        }

    def cleanup_old_events(self, retention_days: int | None = None) -> dict[str, int]:
        retention = retention_days if retention_days is not None else self.settings.cleanup_retention_days
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, retention))
        if self._postgres is not None:
            return self._postgres.cleanup_old_events(cutoff)
        removed = 0
        skipped = 0
        for event_file in sorted(self.events_dir.glob("usage_*.json")):
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
        return {"removed_usage_events": removed, "skipped_usage_events": skipped}

    def metadata(self) -> dict[str, object]:
        if self._postgres is not None:
            return self._postgres.metadata()
        summary = self.summary()
        return {
            "backend": "local",
            "events_dir": self.events_dir.as_posix(),
            "event_count": summary["event_count"],
            "total_units": summary["total_units"],
            "estimated_cost_cents": summary["estimated_cost_cents"],
        }

    def _event_file(self, event: UsageEvent) -> Path:
        return self.events_dir / f"{event.id}.json"

    def _event_to_json(self, event: UsageEvent) -> dict[str, Any]:
        return {
            "id": event.id,
            "action": event.action,
            "actor_id": event.actor_id,
            "resource_type": event.resource_type,
            "resource_id": event.resource_id,
            "units": event.units,
            "estimated_cost_cents": event.estimated_cost_cents,
            "metadata": event.metadata,
            "created_at": event.created_at.isoformat(),
        }

    def _event_from_json(self, payload: dict[str, Any]) -> UsageEvent:
        created_at = datetime.fromisoformat(str(payload["created_at"]))
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return UsageEvent(
            id=str(payload["id"]),
            action=str(payload["action"]),
            actor_id=payload.get("actor_id"),
            resource_type=str(payload["resource_type"]),
            resource_id=payload.get("resource_id"),
            units=int(payload.get("units") or 0),
            estimated_cost_cents=int(payload.get("estimated_cost_cents") or 0),
            metadata=dict(payload.get("metadata") or {}),
            created_at=created_at,
        )
