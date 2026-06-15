from __future__ import annotations

import html
import re
import textwrap
from pathlib import Path


def safe_filename(value: str, max_len: int = 64) -> str:
    value = re.sub(r"[^a-zA-Zа-яА-Я0-9_-]+", "_", value.strip())
    value = value.strip("_") or "file"
    return value[:max_len]


def wrap_text(value: str, width: int = 34) -> list[str]:
    value = re.sub(r"\s+", " ", value.strip())
    lines: list[str] = []
    for paragraph in value.split("\n"):
        lines.extend(textwrap.wrap(paragraph, width=width) or [""])
    return lines


def escape_srt(value: str) -> str:
    return value.replace("\r", "").strip()


def to_srt_timestamp(seconds: int | float) -> str:
    milliseconds = int(round((seconds - int(seconds)) * 1000))
    total = int(seconds)
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def to_vtt_timestamp(seconds: int | float) -> str:
    return to_srt_timestamp(seconds).replace(",", ".")


def make_public_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def xml_escape(value: str) -> str:
    return html.escape(value, quote=True)
