from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


PATTERNS = {
    "openai_api_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "openai_project_key": re.compile(r"\bsk-proj-[A-Za-z0-9_-]{20,}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b"),
    "aws_access_key": re.compile(r"\bA[KS]IA[0-9A-Z]{16}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
}

SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".mp4",
    ".wav",
    ".zip",
    ".lock",
}

SKIP_PARTS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "backend/data/projects",
}


def tracked_files() -> list[Path]:
    result = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    return [Path(line.strip()) for line in result.stdout.splitlines() if line.strip()]


def should_skip(path: Path) -> bool:
    normalized = path.as_posix()
    if path.suffix.lower() in SKIP_SUFFIXES:
        return True
    return any(part in normalized for part in SKIP_PARTS)


def scan_file(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    findings: list[str] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for name, pattern in PATTERNS.items():
            if pattern.search(line):
                findings.append(f"{path.as_posix()}:{line_no}: possible {name}")
    return findings


def main() -> int:
    findings: list[str] = []
    for path in tracked_files():
        if should_skip(path):
            continue
        findings.extend(scan_file(path))
    if findings:
        print("Potential secrets found:", file=sys.stderr)
        for finding in findings:
            print(finding, file=sys.stderr)
        return 1
    print("No tracked secrets found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
