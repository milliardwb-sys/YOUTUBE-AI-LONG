from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.models import (
    SupportTicket,
    SupportTicketCreate,
    SupportTicketNote,
    SupportTicketNoteCreate,
    SupportTicketStatus,
    SupportTicketUpdate,
)
from app.utils.files import ensure_dir, read_json, write_json
from app.utils.security import InvalidIdentifierError, validate_support_ticket_id


class SupportTicketNotFoundError(KeyError):
    pass


class SupportService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.tickets_dir = ensure_dir(settings.data_dir / "_support" / "tickets")
        self._postgres = None
        if settings.support_storage_backend == "postgres":
            from app.postgres_support_store import PostgresSupportRepository

            self._postgres = PostgresSupportRepository(settings)

    def create_ticket(self, payload: SupportTicketCreate, *, created_by: str | None = None) -> SupportTicket:
        note = SupportTicketNote(author=created_by, body=payload.message, internal=False)
        ticket = SupportTicket(
            subject=payload.subject,
            message=payload.message,
            priority=payload.priority,
            user_id=payload.user_id,
            organization_id=payload.organization_id,
            project_id=payload.project_id,
            job_id=payload.job_id,
            tags=payload.tags,
            notes=[note],
        )
        self.save(ticket)
        return ticket

    def get_ticket(self, ticket_id: str) -> SupportTicket:
        try:
            clean_id = validate_support_ticket_id(ticket_id)
        except InvalidIdentifierError as exc:
            raise SupportTicketNotFoundError(ticket_id) from exc
        if self._postgres is not None:
            ticket = self._postgres.get_ticket(clean_id)
            if ticket is None:
                raise SupportTicketNotFoundError(ticket_id)
            return ticket
        path = self._ticket_file(clean_id)
        if not path.exists():
            raise SupportTicketNotFoundError(ticket_id)
        return self._ticket_from_json(read_json(path))

    def list_tickets(
        self,
        *,
        status: SupportTicketStatus | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
    ) -> list[SupportTicket]:
        if self._postgres is not None:
            return self._postgres.list_tickets(status=status, user_id=user_id, project_id=project_id)
        tickets: list[SupportTicket] = []
        for path in sorted(self.tickets_dir.glob("ticket_*.json")):
            try:
                ticket = self._ticket_from_json(read_json(path))
            except (OSError, ValueError, TypeError, KeyError):
                continue
            if status is not None and ticket.status != status:
                continue
            if user_id is not None and ticket.user_id != user_id:
                continue
            if project_id is not None and ticket.project_id != project_id:
                continue
            tickets.append(ticket)
        return sorted(tickets, key=lambda item: (item.updated_at, item.id), reverse=True)

    def update_ticket(self, ticket_id: str, payload: SupportTicketUpdate) -> SupportTicket:
        ticket = self.get_ticket(ticket_id)
        if payload.status is not None:
            ticket.status = payload.status
            if payload.status == SupportTicketStatus.resolved and ticket.resolved_at is None:
                ticket.resolved_at = datetime.now(timezone.utc)
            elif payload.status != SupportTicketStatus.resolved:
                ticket.resolved_at = None
        if payload.priority is not None:
            ticket.priority = payload.priority
        if payload.assignee is not None:
            ticket.assignee = payload.assignee
        if payload.tags is not None:
            ticket.tags = payload.tags
        ticket.touch()
        self.save(ticket)
        return ticket

    def add_note(self, ticket_id: str, payload: SupportTicketNoteCreate, *, author: str | None = None) -> SupportTicket:
        ticket = self.get_ticket(ticket_id)
        ticket.notes.append(SupportTicketNote(author=author, body=payload.body, internal=payload.internal))
        ticket.touch()
        self.save(ticket)
        return ticket

    def save(self, ticket: SupportTicket) -> None:
        if self._postgres is not None:
            self._postgres.save(ticket)
            return
        write_json(self._ticket_file(ticket.id), ticket.model_dump(mode="json"))

    def metadata(self) -> dict[str, object]:
        if self._postgres is not None:
            return self._postgres.metadata()
        tickets = self.list_tickets()
        by_status: dict[str, int] = {}
        for ticket in tickets:
            by_status[ticket.status.value] = by_status.get(ticket.status.value, 0) + 1
        return {
            "backend": "local",
            "tickets_dir": self.tickets_dir.as_posix(),
            "ticket_count": len(tickets),
            "by_status": by_status,
        }

    def _ticket_file(self, ticket_id: str) -> Path:
        return self.tickets_dir / f"{ticket_id}.json"

    def _ticket_from_json(self, payload: dict) -> SupportTicket:
        return SupportTicket.model_validate(payload)
