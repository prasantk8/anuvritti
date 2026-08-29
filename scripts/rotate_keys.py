#!/usr/bin/env python3
"""Zero-Downtime Envelope Key Rotation & Media Re-wrapping CLI (HARDENING 5.5, TASK-1107).

Usage:
  python3 scripts/rotate_keys.py --media-dir /path/to/media --keys "NEW_KEY,OLD_KEY1,OLD_KEY2"

Re-encrypts all media files under the active primary key so retired keys can be retired.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from anuvritti.adapters.media.filesystem import Rewrap, rewrap_directory
from anuvritti.adapters.media.keys import create_keyring


def rotate_media_directory(media_dir: Path, keys_csv: str) -> Rewrap:
    """Re-encrypt every file in media_dir under the active primary key.

    The store owns the walk, so the CLI and the running application rotate media the
    same way and report it the same way. This function only decides what an operator
    at a terminal gets told.
    """
    if not media_dir.exists():
        print(f"Media directory does not exist: {media_dir}", file=sys.stderr)
        return Rewrap(inspected=0, rewrapped=0, failed=())

    report = rewrap_directory(media_dir, create_keyring(keys_csv))

    print(
        f"Inspected {report.inspected} files, re-wrapped {report.rewrapped} under the active key."
    )
    if report.failed:
        print(
            f"\n{len(report.failed)} file(s) opened with no key in the ring:",
            file=sys.stderr,
        )
        for name in report.failed:
            print(f"  {name}", file=sys.stderr)
        print(
            "\nDo NOT retire any historical key. Those bytes are a family's photos and "
            "voice notes, and dropping the key that opens them destroys them.",
            file=sys.stderr,
        )
    else:
        print("Every file opens with the active key. Historical keys can be retired.")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-encrypt media under active key to allow historical key retirement."
    )
    parser.add_argument(
        "--media-dir",
        "-d",
        type=Path,
        default=Path(os.getenv("ANUVRITTI_MEDIA_DIR", "var/media")),
        help="Path to media directory",
    )
    parser.add_argument(
        "--keys",
        "-k",
        type=str,
        default=os.getenv("ANUVRITTI_MEDIA_KEY", ""),
        help="Comma-separated keys (active key first, followed by historical keys)",
    )
    args = parser.parse_args()

    if not args.keys:
        print("Error: Encryption keys required via --keys or ANUVRITTI_MEDIA_KEY", file=sys.stderr)
        sys.exit(1)

    # Non-zero when anything was left behind: a rotation that reports success while
    # a file stayed on an old key is how the next step - retiring that key - loses it.
    if not rotate_media_directory(args.media_dir, args.keys).retirable:
        sys.exit(1)


if __name__ == "__main__":
    main()
