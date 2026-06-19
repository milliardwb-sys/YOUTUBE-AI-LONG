from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.utils.security import UnsafePathError, ensure_within_directory


class ArtifactStoreUnsupportedBackendError(RuntimeError):
    pass


class ArtifactStore:
    """Artifact access abstraction.

    The current implementation is a local backend. It centralizes path validation and
    public URL construction so an S3/R2 adapter can later replace only this layer.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        if settings.artifact_storage_backend != "local":
            raise ArtifactStoreUnsupportedBackendError(
                f"Unsupported artifact storage backend: {settings.artifact_storage_backend}"
            )

    def public_url(self, path_value: str | None) -> str | None:
        if not path_value:
            return None
        try:
            relative = self.relative_path(Path(path_value))
        except (OSError, ValueError, UnsafePathError):
            return None
        return f"{self.settings.public_base_url}/files/{relative.as_posix()}"

    def entry(self, key: str, path_value: str | None) -> dict:
        exists = False
        size_bytes = 0
        if path_value:
            try:
                path = self.resolve_artifact_path(path_value)
                exists = path.is_file()
                size_bytes = path.stat().st_size if exists else 0
            except (OSError, ValueError, UnsafePathError):
                exists = False
                size_bytes = 0
        return {
            "key": key.replace("_path", ""),
            "path": path_value,
            "url": self.public_url(path_value),
            "exists": exists,
            "size_bytes": size_bytes,
            "storage_backend": self.settings.artifact_storage_backend,
        }

    def resolve_file_request(self, file_path: str) -> Path:
        return ensure_within_directory(self.settings.data_dir, self.settings.data_dir / file_path)

    def resolve_artifact_path(self, path_value: str) -> Path:
        return ensure_within_directory(self.settings.data_dir, Path(path_value))

    def relative_path(self, path: Path) -> Path:
        resolved = ensure_within_directory(self.settings.data_dir, path)
        return resolved.relative_to(self.settings.data_dir)

    def metadata(self) -> dict:
        return {
            "backend": self.settings.artifact_storage_backend,
            "url_ttl_seconds": self.settings.artifact_url_ttl_seconds,
            "signed_urls": False,
        }
