#!/usr/bin/env python3
"""Development-only, supervised Techworld hotspot startup.

Default invocation produces a read-only plan. Explicit --execute plus the
typed consent string is required to start services. The rollback stops only
the hotspot started by this invocation, and never changes NetworkManager.
This code is not wired into systemd or the installer yet.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

DIR = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


upstream = load("techworld_upstream_probe", "techworld-upstream-health.py")
post_start = load("techworld_poststart_probe", "techworld-post-start-health.py")

HOTSPOT = "techworld-hotspot"
CONSENT = "START TECHWORLD HOTSPOT"


class StartError(Exception):
    pass


def systemctl(action, service, runner=upstream.run_command):
    return runner(["systemctl", action, service]).strip()


def supervise(uplink, *, execute=False, consent=None, runner=upstream.run_command,
              post_probe=None, delay=lambda _seconds: None, attempts=3,
              root_check=os.geteuid):
    """Check first, optionally start, then monitor, stop on failure.

    Test dependency injection allows thorough simulation without changing
    the running OS. An already active hotspot is never stopped by this tool.
    """
    pre = upstream.inspect(uplink, runner=runner)
    result = {
        "mode": "execute" if execute else "preview",
        "started": False,
        "recovery_attempted": False,
        "preflight": pre,
        "postflight": None,
        "errors": [],
    }
    if not pre["healthy"]:
        result["errors"].append("Upstream is unhealthy before startup")
        return result
    try:
        existing = systemctl("is-active", HOTSPOT, runner)
    except upstream.HealthError as exc:
        result["errors"].append(f"Cannot inspect hotspot state: {exc}")
        return result
    if existing == "active":
        result["errors"].append(
            "Hotspot is already active; refusing to adopt or stop it"
        )
        return result

    if not execute:
        return result

    if consent != CONSENT:
        result["errors"].append("Explicit typed consent is required")
        return result
    if root_check() != 0:
        result["errors"].append("Root permissions are required for startup")
        return result
    if attempts < 1 or attempts > 10:
        result["errors"].append("Invalid post-start attempt count")
        return result

    # Verify the associated Wi-Fi is still healthy immediately before starting.
    second = upstream.inspect(uplink, expected_channel=pre["channel"], runner=runner)
    if not second["healthy"] or second["ssid"] != pre["ssid"] or (
        second["default_gateway"] != pre["default_gateway"]
    ):
        result["errors"].append("Upstream changed during preparation; aborting")
        return result

    started_command = False
    try:
        # systemctl start may partially bring up dependencies before erroring.
        started_command = True
        systemctl("start", HOTSPOT, runner)
        probe = post_probe or (lambda iface: post_start.inspect(iface, runner=runner))
        for i in range(attempts):
            result["postflight"] = probe(uplink)
            if result["postflight"]["healthy"]:
                # A healthy AP can still be missing actual internet reachability.
                result["started"] = True
                return result
            if i < attempts - 1:
                delay(2)
        result["errors"].append("Hotspot post-start health verification failed")
    except (upstream.HealthError, OSError, ValueError) as exc:
        result["errors"].append(f"Startup or health check failed: {exc}")
    finally:
        if started_command and not result["started"]:
            result["recovery_attempted"] = True
            try:
                systemctl("stop", HOTSPOT, runner)
            except upstream.HealthError as exc:
                result["errors"].append(f"Failed to stop Techworld hotspot: {exc}")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Development supervised hotspot start")
    parser.add_argument("--uplink", required=True)
    parser.add_argument("--execute", action="store_true",
                        help="Request real systemd startup; default is read-only")
    parser.add_argument("--confirm", default=None, help="Exact consent phrase")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = supervise(
        args.uplink, execute=args.execute, consent=args.confirm,
        delay=time.sleep
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("Supervised startup:", result["mode"])
        print("Upstream healthy:", result["preflight"]["healthy"])
        print("Hotspot started:", result["started"])
        print("Rollback stop attempted:", result["recovery_attempted"])
        for error in result["errors"]:
            print("ERROR:", error, file=sys.stderr)
        if not args.execute:
            print("PREVIEW ONLY: systemd services were not started.")
    return 0 if (result["started"] or (not args.execute and not result["errors"])) else 1


if __name__ == "__main__":
    sys.exit(main())
