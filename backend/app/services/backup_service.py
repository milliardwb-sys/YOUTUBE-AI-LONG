from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

from app.config import Settings
from app.utils.files import ensure_dir
from app.utils.security import ensure_within_directory

BACKUP_ID_RE = re.compile(r"^backup_[0-9]{8}T[0-9]{6}Z_[a-f0-9]{8}\.zip$")


class BackupNotFoundError(FileNotFoundError):
    pass


class InvalidBackupError(ValueError):
    pass


@dataclass(frozen=True)
class BackupInfo:
    id: str
    path: Path
    size_bytes: int
    created_at: datetime


class BackupService:
    """Local backup/restore-preview service for file-backed MVP data."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.backups_dir = ensure_dir(settings.data_dir / "_backups")
        self.restores_dir = ensure_dir(settings.data_dir / "_restores")

    def create_backup(self) -> dict:
        now = datetime.now(timezone.utc)
        backup_id = f"backup_{now.strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}.zip"
        backup_path = ensure_within_directory(self.backups_dir, self.backups_dir / backup_id)
        files_added = 0
        bytes_added = 0
        with ZipFile(backup_path, "w") as archive:
            for path in sorted(self.settings.data_dir.rglob("*")):
                if not path.is_file() or self._is_internal_backup_path(path):
                    continue
                safe_path = ensure_within_directory(self.settings.data_dir, path)
                relative = safe_path.relative_to(self.settings.data_dir)
                archive.write(safe_path, relative.as_posix())
                files_added += 1
                bytes_added += safe_path.stat().st_size
        return {
            "id": backup_id,
            "path": backup_path.as_posix(),
            "size_bytes": backup_path.stat().st_size,
            "files_added": files_added,
            "source_bytes": bytes_added,
            "created_at": now.isoformat(),
        }

    def list_backups(self) -> list[dict]:
        return [self._backup_to_json(info) for info in self._backup_infos()]

    def backup_path(self, backup_id: str) -> Path:
        self._validate_backup_id(backup_id)
        path = ensure_within_directory(self.backups_dir, self.backups_dir / backup_id)
        if not path.is_file():
            raise BackupNotFoundError(backup_id)
        return path

    def restore_preview(self, backup_id: str) -> dict:
        backup_path = self.backup_path(backup_id)
        restore_id = f"restore_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"
        restore_dir = ensure_within_directory(self.restores_dir, self.restores_dir / restore_id)
        ensure_dir(restore_dir)
        files_restored = 0
        bytes_restored = 0
        with ZipFile(backup_path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                relative = Path(info.filename)
                if relative.is_absolute() or ".." in relative.parts:
                    raise InvalidBackupError(f"Unsafe backup member: {info.filename}")
                target = ensure_within_directory(restore_dir, restore_dir / relative)
                ensure_dir(target.parent)
                with archive.open(info) as source, target.open("wb") as destination:
                    data = source.read()
                    destination.write(data)
                    bytes_restored += len(data)
                    files_restored += 1
        return {
            "backup_id": backup_id,
            "restore_id": restore_id,
            "restore_path": restore_dir.as_posix(),
            "files_restored": files_restored,
            "bytes_restored": bytes_restored,
            "mode": "preview",
        }

    def _backup_infos(self) -> list[BackupInfo]:
        infos: list[BackupInfo] = []
        for path in sorted(self.backups_dir.glob("backup_*.zip")):
            if not path.is_file():
                continue
            try:
                self._validate_backup_id(path.name)
            except InvalidBackupError:
                continue
            stat = path.stat()
            infos.append(
                BackupInfo(
                    id=path.name,
                    path=path,
                    size_bytes=stat.st_size,
                    created_at=datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc),
                )
            )
        return sorted(infos, key=lambda item: item.created_at, reverse=True)

    def _backup_to_json(self, info: BackupInfo) -> dict:
        return {
            "id": info.id,
            "path": info.path.as_posix(),
            "size_bytes": info.size_bytes,
            "created_at": info.created_at.isoformat(),
        }

    def _validate_backup_id(self, backup_id: str) -> None:
        if not BACKUP_ID_RE.fullmatch(backup_id):
            raise InvalidBackupError("Invalid backup id")

    def _is_internal_backup_path(self, path: Path) -> bool:
        relative = path.relative_to(self.settings.data_dir)
        return bool(relative.parts and relative.parts[0] in {"_backups", "_restores"})
