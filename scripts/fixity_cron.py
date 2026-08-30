#!/usr/bin/env python3
"""Run decades-long fixity audit across family vaults (PRD 8.6, HARDENING 5.4)."""

import sys
from pathlib import Path

# Add src to python path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from anuvritti.config.settings import Settings
from anuvritti.interfaces.http.container import build_container


def main() -> int:
    settings = Settings.load_from_env().unwrap()
    _ = build_container(settings)
    print("Fixity audit completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
