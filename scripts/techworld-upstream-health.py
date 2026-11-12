#!/usr/bin/env python3
"""Read-only upstream Wi-Fi health check for Techworld-WiFi.

This utility never changes Wi-Fi connections, systemd services, DNS or firewall.
It is intentionally separate from recovery, which must preserve the user's
upstream connectivity and be tested before integration.
"""
import argparse
import ipaddress
import json
import re
import subprocess
import sys


class HealthError(Exception):
    pass


def run_command(args):
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, check=False, timeout=8
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HealthError(f"{args[0]} inspection unavailable: {exc}") from exc
    if proc.returncode != 0:
        raise HealthError(
            f"{args[0]} inspection failed: {proc.stderr.strip() or proc.returncode}"
        )
    return proc.stdout


def inspect(uplink, expected_channel=None, runner=run_command):
    """Return a fail-closed report based only on read-only system commands."""
    if not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,15}", uplink) or uplink.startswith("-"):
        raise HealthError("Invalid upstream interface name")
    if expected_channel is not None and not (1 <= expected_channel <= 196):
        raise HealthError("Invalid expected channel")

    result = {
        "uplink": uplink,
        "connected": False,
        "ssid": None,
        "channel": None,
        "default_gateway": None,
        "healthy": False,
        "errors": [],
    }
    try:
        nm_output = runner(["nmcli", "-g", "GENERAL.STATE", "device", "show", uplink]).strip()
        if not re.match(r"^100\s*\(connected\)", nm_output):
            result["errors"].append(f"NetworkManager reports {nm_output or 'unknown'}")
        else:
            result["connected"] = True

        iw_info = runner(["iw", "dev", uplink, "info"])
        ssid_match = re.search(r"^\s*ssid\s+(.+)$", iw_info, re.MULTILINE)
        channel_match = re.search(r"^\s*channel\s+(\d+)\b", iw_info, re.MULTILINE)
        if ssid_match:
            result["ssid"] = ssid_match.group(1)
        else:
            result["errors"].append("No upstream Wi-Fi association")
        if channel_match:
            result["channel"] = int(channel_match.group(1))
        else:
            result["errors"].append("Upstream channel unavailable")
        if expected_channel is not None and result["channel"] != expected_channel:
            result["errors"].append(
                f"Upstream channel changed: expected {expected_channel}, got {result['channel']}"
            )

        route_text = runner(["ip", "-j", "-4", "route", "show", "default", "dev", uplink])
        routes = json.loads(route_text)
        valid = []
        for route in routes:
            if route.get("dst") != "default" or route.get("dev") != uplink:
                continue
            via = route.get("gateway")
            if via:
                try:
                    ipaddress.IPv4Address(via)
                except ipaddress.AddressValueError:
                    continue
                valid.append(via)
        if valid:
            result["default_gateway"] = valid[0]
        else:
            result["errors"].append("No IPv4 default gateway on upstream interface")
    except (HealthError, ValueError, TypeError) as exc:
        result["errors"].append(f"Upstream inspection failed: {exc}")

    result["healthy"] = result["connected"] and bool(result["ssid"]) and (
        result["channel"] is not None
    ) and bool(result["default_gateway"]) and not result["errors"]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Read-only Wi-Fi upstream post-start health probe"
    )
    parser.add_argument("--uplink", required=True, help="Verified managed Wi-Fi interface")
    parser.add_argument("--expected-channel", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = inspect(args.uplink, args.expected_channel)
    except HealthError as exc:
        report = {"healthy": False, "errors": [str(exc)], "uplink": args.uplink}
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"Upstream {args.uplink}: {'HEALTHY' if report['healthy'] else 'UNHEALTHY'}"
        )
        for key in ("ssid", "channel", "default_gateway"):
            if key in report:
                print(f"  {key}: {report[key]}")
        for error in report["errors"]:
            print(f"  ERROR: {error}", file=sys.stderr)
    return 0 if report["healthy"] else 1


if __name__ == "__main__":
    sys.exit(main())
