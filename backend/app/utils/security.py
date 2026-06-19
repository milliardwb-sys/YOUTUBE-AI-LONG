from __future__ import annotations

import ipaddress
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

from app.config import Settings

PROJECT_ID_RE = re.compile(r"^project_[a-f0-9]{12}$")
JOB_ID_RE = re.compile(r"^job_[a-f0-9]{12}$")
SCENE_ID_RE = re.compile(r"^scene_[a-f0-9]{8}$")
SOURCE_ID_RE = re.compile(r"^source_[a-f0-9]{8}$")
USER_ID_RE = re.compile(r"^user_[a-f0-9]{12}$")
ORGANIZATION_ID_RE = re.compile(r"^org_[a-f0-9]{12}$")
CONSENT_ID_RE = re.compile(r"^consent_[a-f0-9]{12}$")


class InvalidIdentifierError(ValueError):
    pass


class UnsafePathError(ValueError):
    pass


class UnsafeUrlError(ValueError):
    pass


def validate_project_id(value: str) -> str:
    if not PROJECT_ID_RE.fullmatch(value):
        raise InvalidIdentifierError("Invalid project id")
    return value


def validate_job_id(value: str) -> str:
    if not JOB_ID_RE.fullmatch(value):
        raise InvalidIdentifierError("Invalid job id")
    return value


def validate_scene_id(value: str) -> str:
    if not SCENE_ID_RE.fullmatch(value):
        raise InvalidIdentifierError("Invalid scene id")
    return value


def validate_source_id(value: str) -> str:
    if not SOURCE_ID_RE.fullmatch(value):
        raise InvalidIdentifierError("Invalid source id")
    return value


def validate_user_id(value: str) -> str:
    if not USER_ID_RE.fullmatch(value):
        raise InvalidIdentifierError("Invalid user id")
    return value


def validate_organization_id(value: str) -> str:
    if not ORGANIZATION_ID_RE.fullmatch(value):
        raise InvalidIdentifierError("Invalid organization id")
    return value


def validate_consent_id(value: str) -> str:
    if not CONSENT_ID_RE.fullmatch(value):
        raise InvalidIdentifierError("Invalid consent id")
    return value


def ensure_within_directory(base_dir: Path, candidate: Path) -> Path:
    base = base_dir.resolve()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise UnsafePathError(f"Path escapes storage root: {candidate}") from exc
    return resolved


def validate_source_url(url: str, settings: Settings | None = None, *, resolve_dns: bool = False) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeUrlError("Only http/https source URLs are allowed")
    if parsed.scheme == "http" and settings and not settings.allow_unsafe_http_sources:
        raise UnsafeUrlError("Plain HTTP source URLs are disabled")
    if not parsed.hostname:
        raise UnsafeUrlError("Source URL must include a hostname")
    hostname = parsed.hostname.strip().lower()
    if _is_blocked_host(hostname, settings):
        raise UnsafeUrlError("Private, loopback and local source hosts are disabled")
    if resolve_dns and settings and not settings.allow_private_source_urls:
        for address in _resolve_host(hostname):
            if _is_private_address(address):
                raise UnsafeUrlError("Source URL resolves to a private or local address")
    return url


def _is_blocked_host(hostname: str, settings: Settings | None) -> bool:
    if settings and settings.allow_private_source_urls:
        return False
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost"):
        return True
    try:
        return _is_private_address(ipaddress.ip_address(hostname))
    except ValueError:
        return False


def _is_private_address(address: ipaddress._BaseAddress) -> bool:
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _resolve_host(hostname: str) -> list[ipaddress._BaseAddress]:
    results: list[ipaddress._BaseAddress] = []
    try:
        for item in socket.getaddrinfo(hostname, None):
            raw_address = item[4][0]
            try:
                results.append(ipaddress.ip_address(raw_address))
            except ValueError:
                continue
    except socket.gaierror:
        return []
    return results
