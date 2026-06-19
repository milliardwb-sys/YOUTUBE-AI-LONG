from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.config import ConfigurationError, get_settings  # noqa: E402
from app.storage import ProjectStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate local project_*/project.json records into PostgreSQL.")
    parser.add_argument("--dry-run", action="store_true", help="Read local projects and print what would be migrated.")
    args = parser.parse_args()

    try:
        settings = get_settings()
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if not settings.database_url:
        print("DATABASE_URL is required for migration target.", file=sys.stderr)
        return 2

    source_settings = replace(settings, project_storage_backend="local")
    target_settings = replace(settings, project_storage_backend="postgres")

    source = ProjectStore(source_settings)
    projects = source.list_projects()
    if args.dry_run:
        print(f"Would migrate {len(projects)} project(s).")
        for project in projects:
            print(f"- {project.id} {project.status.value} {project.topic}")
        return 0

    target = ProjectStore(target_settings)
    for project in projects:
        target.save(project)

    print(f"Migrated {len(projects)} project(s) into PostgreSQL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
