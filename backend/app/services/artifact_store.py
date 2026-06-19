from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import quote

from app.config import ConfigurationError, Settings
from app.utils.security import UnsafePathError, ensure_within_directory

try:
    import boto3
except ImportError:  # pragma: no cover - local artifact mode does not need boto3
    boto3 = None


class ArtifactStoreUnsupportedBackendError(RuntimeError):
    pass


class S3ArtifactBackend:
    def __init__(self, settings: Settings):
        if boto3 is None:
            raise ConfigurationError("boto3 is required when ARTIFACT_STORAGE_BACKEND=s3")
        if not settings.s3_bucket:
            raise ConfigurationError("S3_BUCKET is required when ARTIFACT_STORAGE_BACKEND=s3")
        self.settings = settings
        self.bucket = settings.s3_bucket
        self.prefix = settings.s3_prefix.strip("/")
        self.client = boto3.client(
            "s3",
            region_name=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
        )

    def object_key(self, relative: Path) -> str:
        key = relative.as_posix().lstrip("/")
        return f"{self.prefix}/{key}" if self.prefix else key

    def upload_file(self, local_path: Path, object_key: str) -> None:
        content_type, _ = mimetypes.guess_type(local_path.name)
        extra_args = {"ContentType": content_type} if content_type else None
        if extra_args:
            self.client.upload_file(str(local_path), self.bucket, object_key, ExtraArgs=extra_args)
            return
        self.client.upload_file(str(local_path), self.bucket, object_key)

    def head(self, object_key: str) -> tuple[bool, int]:
        try:
            response = self.client.head_object(Bucket=self.bucket, Key=object_key)
            return True, int(response.get("ContentLength") or 0)
        except Exception as exc:  # noqa: BLE001 - S3-compatible providers vary exception classes
            if _is_object_not_found(exc):
                return False, 0
            raise

    def public_url(self, object_key: str) -> str:
        if self.settings.s3_public_base_url:
            return f"{self.settings.s3_public_base_url.rstrip('/')}/{quote(object_key, safe='/')}"
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": object_key},
            ExpiresIn=self.settings.artifact_url_ttl_seconds,
        )

    def metadata(self) -> dict:
        return {
            "backend": "s3",
            "bucket": self.bucket,
            "prefix": self.prefix,
            "endpoint_configured": bool(self.settings.s3_endpoint_url),
            "public_base_url_configured": bool(self.settings.s3_public_base_url),
            "url_ttl_seconds": self.settings.artifact_url_ttl_seconds,
            "signed_urls": not bool(self.settings.s3_public_base_url),
        }


class ArtifactStore:
    """Artifact access abstraction.

    Local mode serves files through the FastAPI `/files` route. S3 mode uploads local
    artifacts to an S3-compatible bucket and returns public or presigned URLs.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._s3: S3ArtifactBackend | None = None
        if settings.artifact_storage_backend == "s3":
            self._s3 = S3ArtifactBackend(settings)
        elif settings.artifact_storage_backend != "local":
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
        if self._s3 is not None:
            return self._s3.public_url(self._s3.object_key(relative))
        return f"{self.settings.public_base_url}/files/{relative.as_posix()}"

    def entry(self, key: str, path_value: str | None) -> dict:
        if self._s3 is not None:
            return self._s3_entry(key, path_value)
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

    def _s3_entry(self, key: str, path_value: str | None) -> dict:
        assert self._s3 is not None
        exists = False
        size_bytes = 0
        object_key = None
        url = None
        if path_value:
            try:
                local_path = self.resolve_artifact_path(path_value)
                relative = self.relative_path(local_path)
                object_key = self._s3.object_key(relative)
                if object_key and local_path.is_file():
                    size_bytes = local_path.stat().st_size
                    self._s3.upload_file(local_path, object_key)
                    exists = True
                elif object_key:
                    exists, size_bytes = self._s3.head(object_key)
                if object_key and exists:
                    url = self._s3.public_url(object_key)
            except (OSError, ValueError, UnsafePathError):
                exists = False
                size_bytes = 0
                object_key = None
                url = None
        return {
            "key": key.replace("_path", ""),
            "path": path_value,
            "url": url,
            "exists": exists,
            "size_bytes": size_bytes,
            "storage_backend": self.settings.artifact_storage_backend,
            "object_key": object_key,
        }

    def resolve_file_request(self, file_path: str) -> Path:
        return ensure_within_directory(self.settings.data_dir, self.settings.data_dir / file_path)

    def resolve_artifact_path(self, path_value: str) -> Path:
        return ensure_within_directory(self.settings.data_dir, Path(path_value))

    def relative_path(self, path: Path) -> Path:
        resolved = ensure_within_directory(self.settings.data_dir, path)
        return resolved.relative_to(self.settings.data_dir)

    def metadata(self) -> dict:
        if self._s3 is not None:
            return self._s3.metadata()
        return {
            "backend": self.settings.artifact_storage_backend,
            "url_ttl_seconds": self.settings.artifact_url_ttl_seconds,
            "signed_urls": False,
        }


def _is_object_not_found(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    error = response.get("Error")
    if not isinstance(error, dict):
        return False
    return str(error.get("Code")) in {"404", "NoSuchKey", "NotFound"}
