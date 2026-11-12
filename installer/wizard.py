#!/usr/bin/env python3
"""Interactive Techworld-WiFi configuration preview.

Updates an existing Techworld-WiFi installation only after explicit approval.
Fresh installation, DHCP/network changes and Laravel are not implemented yet.
"""
import argparse
import ipaddress
import json
import re
import subprocess
import sys
from pathlib import Path

# Allow direct execution and importlib-based offline tests.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from auto_network import DiscoveryError, auto_pool, conflicting_network, discover
from apply_existing import ApplyError, apply_existing

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "scripts" / "techworld-preflight.py"
IFNAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,14}\Z")
LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


class ConfigurationError(ValueError):
    pass


def validate_ssid(value):
    if not value or not (1 <= len(value.encode("utf-8")) <= 32):
        raise ConfigurationError("SSID must be between 1 and 32 UTF-8 bytes")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ConfigurationError("SSID must not contain control characters")
    return value


def validate_domain(value):
    domain = value.strip().lower().rstrip(".")
    if len(domain) > 253 or "." not in domain:
        raise ConfigurationError("Use a valid domain such as wireless.test")
    if any(not LABEL.fullmatch(part) for part in domain.split(".")):
        raise ConfigurationError("Domain contains invalid DNS labels")
    if domain.endswith(".local"):
        raise ConfigurationError(".local uses multicast DNS; use .test for local development")
    return domain


def validate_uplink(value):
    if not IFNAME.fullmatch(value):
        raise ConfigurationError("Upstream network interface name is invalid")
    if value in ("ap0", "br-techworld"):
        raise ConfigurationError("Upstream interface cannot be the managed AP or bridge")
    return value


def validate_network(gateway, start, end):
    try:
        device = ipaddress.IPv4Interface(gateway)
        first, last = ipaddress.IPv4Address(start), ipaddress.IPv4Address(end)
    except ValueError as exc:
        raise ConfigurationError(f"Invalid IPv4 network setting: {exc}") from exc
    network = device.network
    rfc1918 = (
        ipaddress.IPv4Network("10.0.0.0/8"),
        ipaddress.IPv4Network("172.16.0.0/12"),
        ipaddress.IPv4Network("192.168.0.0/16"),
    )
    if not any(device.ip in subnet for subnet in rfc1918):
        raise ConfigurationError("Gateway must use a private RFC1918 address")
    if network.prefixlen > 29:
        raise ConfigurationError("Subnet must have at least six usable addresses")
    if device.ip in (network.network_address, network.broadcast_address):
        raise ConfigurationError("Gateway cannot be the network or broadcast address")
    if first not in network or last not in network or first > last:
        raise ConfigurationError("DHCP start/end must be ordered and within the subnet")
    if first in (network.network_address, network.broadcast_address) or last in (
        network.network_address, network.broadcast_address
    ):
        raise ConfigurationError("DHCP range cannot include network or broadcast address")
    if first <= device.ip <= last:
        raise ConfigurationError("DHCP range cannot include the gateway")
    return str(device), str(first), str(last)


def get_preflight():
    try:
        result = subprocess.run(
            [sys.executable, "-B", str(PREFLIGHT), "--json"],
            capture_output=True, text=True, timeout=25, check=False
        )
        if result.returncode:
            raise ConfigurationError(result.stderr.strip() or "Preflight command failed")
        report = json.loads(result.stdout)
        if not isinstance(report, dict):
            raise ConfigurationError("Preflight returned invalid JSON")
        return report
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Unable to run preflight: {exc}") from exc


def plan(values, preflight):
    status = preflight.get("status")
    if status in ("inspection_failed", "conflict"):
        raise ConfigurationError("Preflight blocked installation due to an inspection error or conflict")
    if status not in ("clean", "adoption_required", "recorded_existing"):
        raise ConfigurationError("Unexpected preflight status")
    ssid = validate_ssid(values["ssid"])
    domain = validate_domain(values["domain"])
    uplink = validate_uplink(values["uplink"])
    gateway, start, end = validate_network(
        values["gateway"], values["dhcp_start"], values["dhcp_end"]
    )
    warnings = ["Preview only: no installation or system changes occurred."]
    if status == "adoption_required":
        warnings.append("Existing legacy installation requires explicit adoption approval.")
    if status == "recorded_existing":
        warnings.append("Existing recorded installation requires update/repair approval.")
    if domain.endswith(".test"):
        warnings.append("The .test domain is local only; use a real HTTPS domain for payments.")
    return {
        "mode": "plan-only",
        "preflight_status": status,
        "wireless": {
            "ssid": ssid,
            "security": "open",
            "uplink": uplink,
            "ap_interface": "ap0",
            "bridge": "br-techworld",
        },
        "portal": {
            "domain": domain, "gateway": gateway,
            "dhcp_start": start, "dhcp_end": end,
            "authentication": "openNDS",
        },
        "requires_explicit_approval_to_install": True,
        "system_changes": [],
        "warnings": warnings,
    }


def ask(prompt, default):
    reply = input(f"{prompt} [{default}]: " if default else f"{prompt} (required): ")
    return reply.strip() or default


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Techworld-WiFi existing-hotspot setup with explicit approval"
    )
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--advanced", action="store_true", help="Offer optional manual network overrides")
    parser.add_argument("--plan-only", action="store_true", help="Preview settings without asking to apply")
    parser.add_argument("--yes", action="store_true", help="Approve existing-installation SSID/DNS update")
    parser.add_argument("--json", action="store_true", help="Machine-readable non-interactive preview")
    for flag in ("ssid", "domain", "uplink", "gateway", "dhcp-start", "dhcp-end"):
        parser.add_argument("--" + flag, dest=flag.replace("-", "_"))
    args = parser.parse_args(argv)
    if args.json and args.yes:
        parser.error("--json is read-only; remove --yes to inspect the plan")
    if args.plan_only and args.yes:
        parser.error("--plan-only cannot be combined with --yes")

    try:
        preflight = get_preflight()
        if preflight.get("status") in ("inspection_failed", "conflict"):
            raise ConfigurationError(
                "Preflight blocked configuration: " + "; ".join(
                    preflight.get("conflicts", []) + preflight.get("errors", [])
                )
            )
        if not args.json:
            print("\nTECHWORLD-WIFI | INTERACTIVE INSTALLATION PREVIEW")
            print(f"Existing installation: {preflight.get('status')}")
            print("Read-only detection completed. Applying changes requires consent.\n")
        detected = discover(preflight["status"])
        defaults = {
            "ssid": "Techworld-WiFi",
            "domain": "wireless.test",
            "uplink": detected["uplink"],
            "gateway": detected["gateway"],
            "dhcp_start": detected["dhcp_start"],
            "dhcp_end": detected["dhcp_end"],
        }
        if not args.json:
            print(
                f"Detected uplink: {detected['uplink']} "
                f"(channel {detected['channel']}, {detected['phy']})"
            )
            print(f"Selected private gateway: {detected['gateway']}")
            print(f"Gateway selection: {detected['source']}")
            if not args.advanced:
                print("Network values are selected automatically. "
                      "Use --advanced to review overrides.\n")
        labels = {
            "ssid": "Wi-Fi SSID",
            "domain": "Captive portal domain",
            "uplink": "Wi-Fi uplink interface",
            "gateway": "Gateway IPv4 address/prefix",
            "dhcp_start": "DHCP range start",
            "dhcp_end": "DHCP range end",
        }
        override_network = False
        if args.advanced and not args.json and not args.non_interactive:
            answer = input("Customize auto-detected network settings? [y/N]: ")
            override_network = answer.strip().lower() in ("y", "yes")

        values = {}
        for key, default in defaults.items():
            given = getattr(args, key)
            prompt = key in ("ssid", "domain") or override_network
            values[key] = given if given is not None else (
                default if args.non_interactive or args.json or not prompt
                else ask(labels[key], default)
            )

        # Never accept a plausible but non-existent uplink name as valid.
        # This preview only supports the verified active Wi-Fi uplink.
        if values["uplink"] != detected["uplink"]:
            raise ConfigurationError(
                f"Uplink {values['uplink']!r} is not the verified active "
                f"Wi-Fi interface {detected['uplink']!r}"
            )

        # Advanced gateway choices must be private and non-overlapping.
        network_overridden = values["gateway"] != detected["gateway"]
        if network_overridden:
            try:
                ipaddress.IPv4Interface(values["gateway"])
            except ValueError as exc:
                raise ConfigurationError(
                    f"Invalid gateway address/prefix: {exc}"
                ) from exc
            conflict = conflicting_network(
                values["gateway"], detected["occupied_networks"],
                allow_bridge=False,
            )
            if conflict:
                raise ConfigurationError(
                    "Gateway overlaps existing routes/interfaces: " + ", ".join(conflict)
                )
            # Keep DHCP in sync if only the gateway was overridden.
            if args.dhcp_start is None and args.dhcp_end is None:
                values["dhcp_start"], values["dhcp_end"] = auto_pool(values["gateway"])
        result = plan(values, preflight)
        result["wireless"]["channel"] = detected["channel"]
        result["wireless"]["radio"] = detected["phy"]
        result["portal"]["gateway_source"] = (
            "advanced user override" if network_overridden else detected["source"]
        )
    except (ConfigurationError, DiscoveryError, EOFError, KeyboardInterrupt) as exc:
        if args.json:
            print(json.dumps({"mode": "plan-only", "error": str(exc)}))
        else:
            print(f"\nCannot create plan: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("\n=== INSTALLATION PLAN ===")
        print("SSID:         " + result["wireless"]["ssid"])
        print("Wi-Fi uplink: " + result["wireless"]["uplink"] +
              f" (channel {result['wireless']['channel']})")
        print("Portal:       " + result["portal"]["domain"])
        print("Gateway:      " + result["portal"]["gateway"])
        print("Gateway mode: " + result["portal"]["gateway_source"])
        print("DHCP range:   " + result["portal"]["dhcp_start"] +
              " - " + result["portal"]["dhcp_end"])
        for note in result["warnings"]:
            print("NOTE: " + note)
        print("\nConfiguration review complete.")
        status = result["preflight_status"]
        if args.plan_only:
            print("Plan-only selected; no changes made.")
        elif status == "clean":
            print(
                "A fresh installation is not implemented yet. "
                "Nothing was installed or changed."
            )
        elif args.non_interactive and not args.yes:
            print(
                "Non-interactive mode is preview-only without --yes. "
                "No changes made."
            )
        else:
            print(
                "\nSupported update: Wi-Fi SSID and local .test DNS alias only."
            )
            print(
                "The existing uplink, gateway, DHCP pool, firewall, "
                "openNDS and system services remain unchanged."
            )
            print(
                "The Wi-Fi access point and/or DHCP service may restart, "
                "briefly disconnecting guests."
            )
            approved = args.yes
            if not approved:
                try:
                    approved = input(
                        "Apply these settings to the existing hotspot? [y/N]: "
                    ).strip().lower() in ("y", "yes")
                except (EOFError, KeyboardInterrupt):
                    print("\nCanceled. No changes made.")
                    return 0
            if not approved:
                print("Canceled. No changes made.")
                return 0
            try:
                applied = apply_existing(result)
            except ApplyError as exc:
                print(f"Update stopped: {exc}", file=sys.stderr)
                return 2
            if applied["changed"]:
                print("SSID/local DNS update applied and services checked.")
                print("Backup: " + applied["backup_directory"])
                print("Note: local DNS mapping does not install a Laravel portal.")
            else:
                print(applied["message"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
