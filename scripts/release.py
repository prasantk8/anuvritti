#!/usr/bin/env python3
"""Blue-Green Release CLI with Automated Error-Budget Rollback (HARDENING 5.4, TASK-1110)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

from anuvritti.infrastructure.release import BlueGreenDeployer, SlotConfig
from anuvritti.observability.slo import (
    SLO_CAPTURE_ACCEPTED,
    AlertSeverity,
    SLOCalculator,
)

CADDY_UPSTREAM_FILE = Path(os.getenv("CADDY_UPSTREAM_FILE", "var/caddy_upstream.json"))


def check_slot_health(slot: SlotConfig) -> bool:
    try:
        url = f"http://127.0.0.1:{slot.port}/ready"
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def cutover_caddy(slot: SlotConfig) -> bool:
    """Switch Caddy reverse proxy upstream to the target slot port."""
    print(f"Switching active upstream traffic to slot '{slot.name}' on port {slot.port}...")
    try:
        CADDY_UPSTREAM_FILE.parent.mkdir(parents=True, exist_ok=True)
        CADDY_UPSTREAM_FILE.write_text(
            json.dumps({"active_slot": slot.name, "port": slot.port, "version": slot.version})
        )
        return True
    except Exception as exc:
        print(f"Cutover failed writing upstream state: {exc}", file=sys.stderr)
        return False


def evaluate_slot_slo_burn(metrics_text: str, window_hours: float = 1.0) -> bool:
    """Evaluate whether candidate slot is burning error budget at a paging rate."""
    total_requests = 0
    total_errors = 0

    for line in metrics_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("anuvritti_http_requests_total") or line.startswith(
            "anuvritti_http_requests_handled"
        ):
            match = re.search(r"\s+(\d+(?:\.\d+)?)$", line)
            if match:
                total_requests += int(float(match.group(1)))

        if line.startswith("anuvritti_http_requests_errors_total"):
            match = re.search(r"\s+(\d+(?:\.\d+)?)$", line)
            if match:
                total_errors += int(float(match.group(1)))

    if total_requests == 0:
        return True

    good_events = max(0, total_requests - total_errors)
    sli = SLOCalculator.evaluate(
        slo=SLO_CAPTURE_ACCEPTED,
        total_events=total_requests,
        good_events=good_events,
        window_hours=window_hours,
    )
    return sli.severity != AlertSeverity.PAGE


def monitor_burn(slot: SlotConfig) -> bool:
    """Monitor error budget burn on candidate slot by reading its /metrics endpoint."""
    print(f"Monitoring error budget burn on slot '{slot.name}' (port {slot.port})...")
    try:
        url = f"http://127.0.0.1:{slot.port}/metrics"
        with urllib.request.urlopen(url, timeout=5) as resp:
            if resp.status != 200:
                return False
            metrics_text = resp.read().decode("utf-8", errors="ignore")
            is_healthy = evaluate_slot_slo_burn(metrics_text)
            if not is_healthy:
                print(f"CRITICAL: Error budget burn on '{slot.name}'!", file=sys.stderr)
            return is_healthy
    except Exception:
        return False


def rollback_caddy(slot: SlotConfig) -> bool:
    """Immediately restore traffic to the stable slot."""
    print(f"ROLLBACK: Restoring traffic to slot '{slot.name}' on port {slot.port}!")
    try:
        CADDY_UPSTREAM_FILE.parent.mkdir(parents=True, exist_ok=True)
        CADDY_UPSTREAM_FILE.write_text(
            json.dumps(
                {
                    "active_slot": slot.name,
                    "port": slot.port,
                    "version": slot.version,
                    "status": "rolled_back",
                }
            )
        )
        return True
    except Exception as exc:
        print(f"Rollback failed writing upstream state: {exc}", file=sys.stderr)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Execute Blue-Green Deploy with SLO Error Budget Monitoring"
    )
    parser.add_argument("--active-port", type=int, default=8001)
    parser.add_argument("--candidate-port", type=int, default=8002)
    parser.add_argument("--version", type=str, default="v0.3.0")
    args = parser.parse_args()

    blue = SlotConfig(name="blue", port=args.active_port, version="active")
    green = SlotConfig(name="green", port=args.candidate_port, version=args.version)

    deployer = BlueGreenDeployer(blue, green)
    ok, msg = deployer.execute_release(
        health_check_fn=check_slot_health,
        cutover_fn=cutover_caddy,
        monitor_burn_fn=monitor_burn,
        rollback_fn=rollback_caddy,
    )

    if not ok:
        print(f"DEPLOYMENT FAILED: {msg}", file=sys.stderr)
        sys.exit(1)

    print(f"DEPLOYMENT SUCCEEDED: {msg}")


if __name__ == "__main__":
    main()
