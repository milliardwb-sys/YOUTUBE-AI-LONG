from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.config import ConfigurationError, get_settings  # noqa: E402
from app.services.usage_service import UsageService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate local _usage/usage_*.json records into PostgreSQL.")
    parser.add_argument("--dry-run", action="store_true", help="Read local usage events and print what would migrate.")
    args = parser.parse_args()

    try:
        settings = get_settings()
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if not settings.database_url:
        print("DATABASE_URL is required for migration target.", file=sys.stderr)
        return 2

    source_settings = replace(settings, usage_storage_backend="local")
    target_settings = replace(settings, usage_storage_backend="postgres")

    source = UsageService(source_settings)
    events = source.list_events()
    if args.dry_run:
        print(f"Would migrate {len(events)} usage event(s).")
        for event in events:
            print(f"- {event.id} {event.action} units={event.units} cost={event.estimated_cost_cents}")
        return 0

    target = UsageService(target_settings)
    for event in events:
        target.save_event(event)

    print(f"Migrated {len(events)} usage event(s) into PostgreSQL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
