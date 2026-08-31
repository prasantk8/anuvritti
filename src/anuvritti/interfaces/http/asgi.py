"""ASGI entrypoint: `uvicorn anuvritti.interfaces.http.asgi:app`."""

from __future__ import annotations

import os
import sys

from anuvritti.config.settings import load_settings
from anuvritti.interfaces.http.app import create_app

_settings = load_settings(dict(os.environ))
if _settings.is_err():
    # Refuse to start rather than run a process that cannot honour PRD 44.
    print(f"configuration error: {_settings.unwrap_err().message}", file=sys.stderr)
    os._exit(78)  # EX_CONFIG
app = create_app(_settings.unwrap())
