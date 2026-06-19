from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.config import ConfigurationError, get_settings  # noqa: E402
from app.services.idempotency_service import IdempotencyStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate local _idempotency/*.json records into PostgreSQL.")
    parser.add_argument("--dry-run", action="store_true", help="Read local records and print what would migrate.")
    args = parser.parse_args()

    try:
        settings = get_settings()
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if not settings.database_url:
        print("DATABASE_URL is required for migration target.", file=sys.stderr)
        return 2

    source_settings = replace(settings, idempotency_storage_backend="local")
    target_settings = replace(settings, idempotency_storage_backend="postgres")
    source = IdempotencyStore(source_settings)
    records = source.list_records()

    if args.dry_run:
        print(f"Would migrate {len(records)} idempotency record(s).")
        for record in records:
            print(f"- {record.key_hash} {record.scope} {record.resource_type}:{record.resource_id}")
        return 0

    target = IdempotencyStore(target_settings)
    for record in records:
        target.save_record(record)

    print(f"Migrated {len(records)} idempotency record(s) into PostgreSQL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
