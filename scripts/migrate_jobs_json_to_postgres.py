from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.config import ConfigurationError, get_settings  # noqa: E402
from app.services.job_service import JobStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate local _jobs/job_*.json records into PostgreSQL.")
    parser.add_argument("--dry-run", action="store_true", help="Read local jobs and print what would be migrated.")
    args = parser.parse_args()

    try:
        settings = get_settings()
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if not settings.database_url:
        print("DATABASE_URL is required for migration target.", file=sys.stderr)
        return 2

    source_settings = replace(settings, job_storage_backend="local")
    target_settings = replace(settings, job_storage_backend="postgres")

    source = JobStore(source_settings)
    jobs = source.list_all()
    if args.dry_run:
        print(f"Would migrate {len(jobs)} job(s).")
        for job in jobs:
            print(f"- {job.id} {job.status.value} {job.type.value} project={job.project_id}")
        return 0

    target = JobStore(target_settings)
    for job in jobs:
        target.save(job)

    print(f"Migrated {len(jobs)} job(s) into PostgreSQL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
