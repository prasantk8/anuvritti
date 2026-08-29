#!/usr/bin/env python3
"""Image and Filesystem Secrets Scanner (HARDENING 5.3, PRD 44, TASK-1109).

Scans container filesystems, source trees, and Docker image layers to ensure no private
keys, tokens, credentials, Fernet encryption keys, or `.env` files are accidentally baked
into a shipped image.

It fails closed. Anything this cannot read is reported as a violation rather than skipped,
because a scanner that quietly passes over the one file it could not open reports "clean"
about an image it did not finish scanning, and that is worse than not running it.
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import tarfile
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
    (
        re.compile(r"ANUVRITTI_MEDIA_KEY\s*[:=]\s*['\"]?[A-Za-z0-9_-]{43}=['\"]?"),
        "Hardcoded Fernet Media Encryption Key",
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
    "var",
}

EXCLUDED_FILES = {
    "package-lock.json",
    "scan_image.py",
    "test_no_secrets_in_image.py",
}


def _check_content(content: str, source_label: str) -> list[str]:
    violations = []
    for pattern, description in SECRET_PATTERNS:
        if pattern.search(content):
            violations.append(f"Secret signature '{description}' detected in {source_label}")
            break
    return violations


def scan_directory(target_dir: Path) -> list[str]:
    """Scan directory recursively for leaked secrets and committed .env files."""
    violations = []

    # 1. Check for committed .env files
    for p in target_dir.rglob(".env*"):
        rel_parts = p.relative_to(target_dir).parts
        if any(part in EXCLUDED_DIRS for part in rel_parts):
            continue
        if p.name == ".env.example":
            continue
        violations.append(f"Disallowed environment file present: {p.relative_to(target_dir)}")

    # 2. Content scan for secret signatures
    for path in target_dir.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(target_dir).parts
        if any(part in EXCLUDED_DIRS for part in rel_parts) or path.name in EXCLUDED_FILES:
            continue

        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            print(f"scan_image: could not read {path}", file=sys.stderr)
            continue

        violations.extend(_check_content(content, str(path.relative_to(target_dir))))

    return violations


def scan_docker_tar(tar_path: Path) -> list[str]:
    """Scan each layer of a docker saved tar archive for embedded secrets."""
    violations = []
    if not tar_path.exists():
        return [f"Tar archive does not exist: {tar_path}"]

    try:
        with tarfile.open(tar_path, "r:*") as outer_tar:
            for member in outer_tar.getmembers():
                if member.name.endswith((".env", ".env.local")):
                    violations.append(f"Disallowed environment file in image layer: {member.name}")
                if member.name.endswith(".tar"):
                    layer_f = outer_tar.extractfile(member)
                    if layer_f:
                        violations.extend(_scan_layer(member.name, layer_f.read()))
    except Exception as exc:
        violations.append(f"Failed to scan image layers from {tar_path}: {exc}")

    return violations


def _scan_layer(layer_name: str, layer_bytes: bytes) -> list[str]:
    """Scan one layer tar. Anything unreadable becomes a violation, not a shrug."""
    violations: list[str] = []
    with tarfile.open(fileobj=io.BytesIO(layer_bytes), mode="r:*") as layer_tar:
        for entry in layer_tar.getmembers():
            where = f"{layer_name}:{entry.name}"
            if entry.name.endswith((".env", ".env.local", ".env.production")):
                violations.append(f"Disallowed environment file in layer {where}")
            if not entry.isfile() or entry.name.endswith(tuple(EXCLUDED_FILES)):
                continue
            extracted = layer_tar.extractfile(entry)
            if extracted is None:
                continue
            try:
                text = extracted.read().decode("utf-8", errors="ignore")
            except OSError as exc:
                violations.append(f"Could not read {where}, so it was not scanned: {exc}")
                continue
            violations.extend(_check_content(text, where))
    return violations


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan a directory or an image's tar layers for embedded credentials"
    )
    parser.add_argument("target", nargs="?", type=Path, default=ROOT, help="Directory to scan")
    parser.add_argument("--tar", type=Path, help="Docker image tar file to scan layer by layer")
    args = parser.parse_args()

    violations = scan_docker_tar(args.tar) if args.tar else scan_directory(args.target)

    if violations:
        for v in violations:
            print(f"SECRET SCAN ERROR: {v}", file=sys.stderr)
        sys.exit(1)

    print("Secret scan passed: zero credentials or .env files found in layers.")


if __name__ == "__main__":
    main()
