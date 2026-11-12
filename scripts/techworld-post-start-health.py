#!/usr/bin/env python3
"""Read-only post-start hotspot health assessment, not an automatic recovery agent.

Inspect *both* upstream connectivity and AP state. No service restarts,
NetworkManager connection changes, firewall changes or packet transmission.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

upstream_path = Path(__file__).with_name("techworld-upstream-health.py")
spec = importlib.util.spec_from_file_location("techworld_upstream_health", upstream_path)
upstream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upstream)

SERVICES = (
    "techworld-hotspot",
    "techworld-ap",
    "techworld-hostapd",
    "techworld-dhcp",
    "opennds",
)


def inspect(uplink, ap="ap0", runner=upstream.run_command):
    """Fail closed if the upstream or any hotspot component is unavailable."""
    details = {"healthy": False, "upstream": {}, "ap": {}, "services": {}, "errors": []}
    if not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,15}", ap) or ap.startswith("-"):
        details["errors"].append("Invalid AP interface name")
        return details
    try:
        upstream_status = upstream.inspect(uplink, runner=runner)
    except upstream.HealthError as exc:
        details["errors"].append(str(exc))
        return details
    details["upstream"] = upstream_status
    if not upstream_status["healthy"]:
        details["errors"].append("Upstream association or default route is unhealthy")
    for service in SERVICES:
        try:
            state = runner(["systemctl", "is-active", service]).strip()
        except upstream.HealthError as exc:
            state = "inspection-failed"
            details["errors"].append(f"{service}: {exc}")
        details["services"][service] = state
        if state != "active":
            details["errors"].append(f"Service {service} is {state}")

    try:
        ap_info = runner(["iw", "dev", ap, "info"])
        channel_match = re.search(r"^\s*channel\s+(\d+)\b", ap_info, re.MULTILINE)
        type_match = re.search(r"^\s*type\s+(\S+)\s*$", ap_info, re.MULTILINE)
        ap_channel = int(channel_match.group(1)) if channel_match else None
        ap_type = type_match.group(1) if type_match else None
        details["ap"] = {"interface": ap, "type": ap_type, "channel": ap_channel}
        if ap_type != "AP":
            details["errors"].append("Hotspot interface is not operating in AP mode")
        if ap_channel is None or ap_channel != upstream_status["channel"]:
            details["errors"].append("Hotspot AP channel does not match upstream channel")
    except upstream.HealthError as exc:
        details["errors"].append(f"Cannot inspect AP interface: {exc}")

    details["healthy"] = not details["errors"]
    return details


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only Techworld hotspot health assessment")
    parser.add_argument("--uplink", required=True)
    parser.add_argument("--ap", default="ap0")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = inspect(args.uplink, args.ap)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("Techworld-WiFi post-start check:", "HEALTHY" if report["healthy"] else "UNHEALTHY")
        for error in report["errors"]:
            print("ERROR:", error, file=sys.stderr)
    return 0 if report["healthy"] else 1


if __name__ == "__main__":
    sys.exit(main())
