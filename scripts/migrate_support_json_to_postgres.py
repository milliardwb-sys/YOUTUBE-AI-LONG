from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.config import ConfigurationError, get_settings  # noqa: E402
from app.services.support_service import SupportService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate local _support/tickets/ticket_*.json records into PostgreSQL.")
    parser.add_argument("--dry-run", action="store_true", help="Read local support tickets and print what would migrate.")
    args = parser.parse_args()

    try:
        settings = get_settings()
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if not settings.database_url:
        print("DATABASE_URL is required for migration target.", file=sys.stderr)
        return 2

    source_settings = replace(settings, support_storage_backend="local")
    target_settings = replace(settings, support_storage_backend="postgres")

    source = SupportService(source_settings)
    tickets = source.list_tickets()
    if args.dry_run:
        print(f"Would migrate {len(tickets)} support ticket(s).")
        for ticket in tickets:
            print(f"- {ticket.id} {ticket.status.value} {ticket.priority.value} {ticket.subject}")
        return 0

    target = SupportService(target_settings)
    for ticket in tickets:
        target.save(ticket)

    print(f"Migrated {len(tickets)} support ticket(s) into PostgreSQL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
