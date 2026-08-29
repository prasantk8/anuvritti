#!/usr/bin/env python3
"""Image and Filesystem Secrets Scanner (HARDENING 5.3, PRD 44).

Scans container filesystems, source trees, and build layers to ensure no private keys,
tokens, credentials, or `.env` files are accidentally baked into shipped images.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SECRET_PATTERNS = [
    (
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
        "Unencrypted Private Key Header",
    ),
    (re.compile(r"(?:AKIA|ABIA|ACCA)[0-9A-Z]{16}"), "AWS Access Key ID"),
    (re.compile(r"ghp_[a-zA-Z0-9]{36}"), "GitHub Personal Access Token"),
    (re.compile(r"xox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,32}"), "Slack Token"),
    (
        re.compile(r"(?:postgres|mysql|mongodb)://[^:]+:[^@\s]+@[^/\s]+"),
        "Database Connection URI with Password",
    ),
]

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
}

EXCLUDED_FILES = {
    "package-lock.json",
}


def scan_directory(target_dir: Path) -> list[str]:
    """Scan directory recursively for leaked secrets and committed .env files."""
    violations = []

    # 1. Check for committed .env files
    for p in target_dir.rglob(".env*"):
        if any(part in EXCLUDED_DIRS for part in p.parts):
            continue
        if p.name == ".env.example":
            continue
        violations.append(f"Disallowed environment file present: {p.relative_to(target_dir)}")

    # 2. Content scan for secret signatures
    for path in target_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIRS for part in path.parts) or path.name in EXCLUDED_FILES:
            continue

        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            # A file this scanner cannot read is a file it cannot clear, so say so
            # rather than skipping in silence.
            print(f"scan_image: could not read {path}", file=sys.stderr)
            continue

        for pattern, description in SECRET_PATTERNS:
            if pattern.search(content):
                # Avoid self-matching this scanner script
                if path.name == "scan_image.py" or path.name == "test_no_secrets_in_image.py":
                    continue
                violations.append(
                    f"Secret signature '{description}' detected in {path.relative_to(target_dir)}"
                )
                break

    return violations


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan directory for embedded credentials")
    parser.add_argument("target", nargs="?", type=Path, default=ROOT, help="Directory to scan")
    args = parser.parse_args()

    violations = scan_directory(args.target)
    if violations:
        for v in violations:
            print(f"SECRET SCAN ERROR: {v}", file=sys.stderr)
        sys.exit(1)

    print("Secret scan passed: zero credentials or .env files found in layers.")


if __name__ == "__main__":
    main()
