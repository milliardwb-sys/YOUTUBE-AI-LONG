from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    value = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    _atomic_write_text(path, value)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, value: str) -> None:
    ensure_dir(path.parent)
    _atomic_write_text(path, value)


def _atomic_write_text(path: Path, value: str) -> None:
    ensure_dir(path.parent)
    tmp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    tmp_path.write_text(value, encoding="utf-8")
    os.replace(tmp_path, path)
