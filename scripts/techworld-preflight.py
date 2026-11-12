#!/usr/bin/env python3
"""Read-only installation and conflict inventory for Techworld-WiFi.

Never stop, enable, disable, reload, delete, or write system resources here.
The future interactive installer must get confirmation before adopting or
replacing legacy installation files.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

OWNER = "techworld-wifi"
MANIFEST = Path("/var/lib/techworld-wifi/install-manifest.json")
UNITS = (
    "techworld-hotspot.service",
    "techworld-ap.service",
    "techworld-isolation.service",
    "techworld-nat.service",
    "techworld-hostapd.service",
    "techworld-dhcp.service",
    "opennds.service",
)
PROJECT_UNITS = tuple(unit for unit in UNITS if unit.startswith("techworld-"))
SHARED_UNITS = ("dnsmasq.service", "hostapd.service", "NetworkManager.service")
FILES = (
    "/etc/hostapd/techworld.conf",
    "/etc/techworld-hotspot/dnsmasq.conf",
    "/etc/config/opennds",
    "/usr/local/sbin/techworld-ap-prepare",
    "/usr/local/sbin/techworld-ipv4-guard",
)
EXIT_STATUS = {
    "clean": 0,
    "recorded_existing": 10,
    "adoption_required": 20,
    "conflict": 30,
    "inspection_failed": 40,
}


def run_command(args):
    """Only run known read-only inspection commands."""
    try:
        return subprocess.run(
            args, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=6, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(args, 127, "", str(exc))


def unit_state(name, runner):
    result = runner([
        "systemctl", "show", "--no-pager", name,
        "--property=LoadState,ActiveState,FragmentPath",
    ])
    values = dict(
        line.split("=", 1)
        for line in result.stdout.splitlines()
        if "=" in line
    )
    load = values.get("LoadState", "unknown")
    exists = load not in ("not-found", "unknown", "masked") or bool(
        values.get("FragmentPath", "")
    )
    error = None
    if load == "unknown" or (result.returncode and load != "not-found"):
        error = f"Cannot inspect {name}: {result.stderr.strip() or 'unknown systemctl error'}"
    # A masked unit still needs attention because its name is occupied.
    if load == "masked":
        exists = True
    return {
        "name": name,
        "exists": exists,
        "load_state": load,
        "active_state": values.get("ActiveState", "unknown"),
        "fragment_path": values.get("FragmentPath", ""),
    }, error


def read_manifest(path):
    if not path.exists():
        return None, None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(manifest, dict)
                or manifest.get("owner") != OWNER
                or manifest.get("schema_version") != 1
                or not isinstance(manifest.get("units"), list)
                or not all(isinstance(u, str) for u in manifest["units"])):
            raise ValueError("unexpected owner, schema or units")
        return manifest, None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return None, f"Installation manifest cannot be trusted: {exc}"


def interface_exists(name, runner):
    result = runner(["ip", "-j", "link", "show", "dev", name])
    if result.returncode == 0:
        return True, None
    # 'Device does not exist' is expected for an unconfigured machine.
    msg = (result.stdout + " " + result.stderr).lower()
    if "does not exist" in msg or "cannot find device" in msg:
        return False, None
    return False, f"Cannot inspect interface {name}: {result.stderr.strip()}"


def port_2050_listening(runner):
    result = runner(["ss", "-H", "-ltn", "sport = :2050"])
    if result.returncode:
        return False, f"Cannot inspect TCP port 2050: {result.stderr.strip()}"
    return bool(result.stdout.strip()), None


def valid_ifname(value):
    return bool(re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,14}", value))


def inspect(manifest_path=MANIFEST, ap_iface="ap0", bridge="br-techworld",
            runner=run_command):
    units = []
    shared = []
    errors = []
    manifest, manifest_error = read_manifest(manifest_path)
    if manifest_error:
        errors.append(manifest_error)

    for unit in UNITS:
        state, error = unit_state(unit, runner)
        units.append(state)
        if error:
            errors.append(error)
    for unit in SHARED_UNITS:
        state, error = unit_state(unit, runner)
        if state["exists"]:
            shared.append(state)
        if error:
            errors.append(error)

    interfaces = []
    for iface in (ap_iface, bridge):
        present, error = interface_exists(iface, runner)
        interfaces.append({"name": iface, "exists": present})
        if error:
            errors.append(error)

    port_in_use, error = port_2050_listening(runner)
    if error:
        errors.append(error)

    known_files = [path for path in FILES if Path(path).exists()]
    existing_units = [item for item in units if item["exists"]]
    project_units_exist = any(item["name"] in PROJECT_UNITS for item in existing_units)
    opennds_exists = any(item["name"] == "opennds.service" for item in existing_units)

    conflicts = []
    if any(item["exists"] for item in interfaces) and not project_units_exist:
        conflicts.append("Reserved hotspot interface name already in use without Techworld unit")
    if port_in_use and not opennds_exists:
        conflicts.append("TCP port 2050 is listening but no opennds.service is installed")
    if opennds_exists and not project_units_exist and manifest is None:
        conflicts.append("opennds.service exists without Techworld units; ownership unknown")

    # Manifest is a hint, never authorization to delete or replace files.
    recorded_units = set(manifest["units"]) if manifest else set()
    unrecorded = [u["name"] for u in existing_units if u["name"] not in recorded_units]
    if manifest and not existing_units:
        conflicts.append("Installation manifest exists but no managed units are installed")
    if manifest and unrecorded:
        conflicts.append("Existing units are not recorded in the installation manifest")

    if errors:
        status = "inspection_failed"
    elif conflicts:
        status = "conflict"
    elif existing_units or known_files:
        status = "recorded_existing" if manifest else "adoption_required"
    else:
        status = "clean"

    return {
        "schema_version": 1,
        "status": status,
        "exit_code_strict": EXIT_STATUS[status],
        "manifest_present": manifest is not None,
        "existing_units": existing_units,
        "shared_units": shared,
        "reserved_interfaces": interfaces,
        "port_2050_listening": port_in_use,
        "existing_files": known_files,
        "conflicts": conflicts,
        "errors": errors,
        "requires_explicit_confirmation": status != "clean",
        "actions_performed": [],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Machine-readable result")
    parser.add_argument("--strict", action="store_true", help="Nonzero exit when review is needed")
    parser.add_argument("--ap-iface", default="ap0")
    parser.add_argument("--bridge", default="br-techworld")
    args = parser.parse_args(argv)
    for value in (args.ap_iface, args.bridge):
        if not valid_ifname(value):
            parser.error("Invalid network interface name")

    if not shutil.which("systemctl") or not shutil.which("ip") or not shutil.which("ss"):
        report = {"status": "inspection_failed", "errors": [
            "Required read-only commands systemctl, ip and ss must be available"
        ], "exit_code_strict": 40, "actions_performed": []}
    else:
        report = inspect(ap_iface=args.ap_iface, bridge=args.bridge)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Techworld-WiFi preflight: {report['status'].replace('_', ' ')}")
        for unit in report.get("existing_units", []):
            print(f"  Existing: {unit['name']} ({unit['active_state']})")
        for shared in report.get("shared_units", []):
            print(f"  Shared service (preserved): {shared['name']} ({shared['active_state']})")
        for item in report.get("reserved_interfaces", []):
            if item["exists"]:
                print(f"  Interface in use: {item['name']}")
        for message in report.get("conflicts", []):
            print(f"  CONFLICT: {message}")
        for message in report.get("errors", []):
            print(f"  ERROR: {message}")
        if report["status"] != "clean":
            print("No changes made. Review and explicitly approve any adoption or replacement.")
        else:
            print("No existing Techworld-WiFi resources detected.")
    return report["exit_code_strict"] if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
