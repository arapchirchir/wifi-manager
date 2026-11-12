"""Guarded update for an existing, running Techworld-WiFi installation.

Only updates SSID and .test DNS alias. Does not replace packages, network
interfaces, gateway, DHCP pool, openNDS configuration or services.
Requires separate, explicit interactive confirmation from the caller.
"""
import ipaddress
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class ApplyError(RuntimeError):
    pass


HOSTAPD = Path("/etc/hostapd/techworld.conf")
DNSMASQ = Path("/etc/techworld-hotspot/dnsmasq.conf")
HOSTAPD_UNIT = Path("/etc/systemd/system/techworld-hostapd.service")
DNSMASQ_UNIT = Path("/etc/systemd/system/techworld-dhcp.service")
BACKUPS = Path("/var/backups/techworld-wifi")
START_MARKER = "# BEGIN TECHWORLD-WIFI MANAGED PORTAL DNS"
END_MARKER = "# END TECHWORLD-WIFI MANAGED PORTAL DNS"


def command(args):
    """Run a known system command without invoking a shell."""
    try:
        p = subprocess.run(
            args, capture_output=True, text=True, check=False, timeout=25
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ApplyError(f"Failed to run {args[0]}: {exc}") from exc
    if p.returncode:
        raise ApplyError(
            f"{args[0]} returned {p.returncode}: "
            f"{p.stderr.strip() or p.stdout.strip()}"
        )
    return p.stdout


def verify_target(plan, active_command=command):
    if os.geteuid() != 0:
        raise ApplyError("Administrative permission required: rerun with sudo ./install.sh")
    if plan.get("preflight_status") not in ("adoption_required", "recorded_existing"):
        raise ApplyError("Safe updates are supported only for existing Techworld installations")
    if plan["wireless"]["ap_interface"] != "ap0" or plan["wireless"]["bridge"] != "br-techworld":
        raise ApplyError("Unexpected managed interface names")
    try:
        gateway = ipaddress.IPv4Interface(plan["portal"]["gateway"])
    except ValueError as exc:
        raise ApplyError(f"Invalid gateway: {exc}") from exc
    if gateway.network.prefixlen != 24:
        raise ApplyError("Existing gateway must be /24 for this update")
    if not plan["portal"]["domain"].endswith(".test"):
        raise ApplyError(
            "This update only supports .test DNS aliases. Public domains require HTTPS setup."
        )

    for path in (HOSTAPD, DNSMASQ, HOSTAPD_UNIT, DNSMASQ_UNIT):
        if path.is_symlink() or not path.is_file():
            raise ApplyError(f"Missing or unsafe installation file: {path}")
    hostapd_unit = HOSTAPD_UNIT.read_text()
    dnsmasq_unit = DNSMASQ_UNIT.read_text()
    if str(HOSTAPD) not in hostapd_unit or str(DNSMASQ) not in dnsmasq_unit:
        raise ApplyError("Service files do not reference expected Techworld configurations")

    for service in (
        "techworld-hotspot", "techworld-hostapd", "techworld-dhcp", "opennds"
    ):
        if active_command(["systemctl", "is-active", service]).strip() != "active":
            raise ApplyError(f"Expected running service {service} is not active")

    # Re-verify the actual local bridge address immediately before writing.
    try:
        addresses = json.loads(active_command(
            ["ip", "-j", "-4", "address", "show", "dev", "br-techworld"]
        ))
        actual = {
            str(ipaddress.IPv4Interface(f"{a['local']}/{a['prefixlen']}"))
            for interface in addresses
            for a in interface.get("addr_info", [])
            if a.get("family") == "inet"
        }
    except (ValueError, KeyError) as exc:
        raise ApplyError(f"Cannot verify the current bridge address: {exc}") from exc
    if str(gateway) not in actual:
        raise ApplyError(
            f"Planned gateway {gateway} does not match the active bridge: {sorted(actual)}"
        )

    # Only the existing subnet's currently configured DHCP range is supported.
    # A future migration tool will safely change gateway, DHCP and firewall together.
    try:
        dns_source = DNSMASQ.read_text()
        current_range = [
            line.strip() for line in dns_source.splitlines()
            if re.match(r"^\s*dhcp-range\s*=", line) and not line.lstrip().startswith("#")
        ]
    except OSError as exc:
        raise ApplyError(f"Cannot read dedicated dnsmasq configuration: {exc}") from exc
    if len(current_range) != 1:
        raise ApplyError("Expected exactly one existing DHCP range")
    range_ips = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", current_range[0])
    if len(range_ips) < 2 or range_ips[0:2] != [
        plan["portal"]["dhcp_start"], plan["portal"]["dhcp_end"]
    ]:
        raise ApplyError("Changing DHCP settings is not yet supported by the safe update")
    return dns_source


def updated_ssid(original, ssid, channel):
    lines = original.splitlines(keepends=True)
    indices = [
        i for i, line in enumerate(lines)
        if re.match(r"^\s*ssid\s*=", line) and not line.lstrip().startswith("#")
    ]
    if len(indices) != 1:
        raise ApplyError("Expected exactly one active hostapd SSID setting")
    iface = [
        line.split("=", 1)[1].strip() for line in lines
        if re.match(r"^\s*interface\s*=", line) and not line.lstrip().startswith("#")
    ]
    channels = [
        line.split("=", 1)[1].strip() for line in lines
        if re.match(r"^\s*channel\s*=", line) and not line.lstrip().startswith("#")
    ]
    if iface != ["ap0"] or channels != [str(channel)]:
        raise ApplyError(
            f"Hostapd interface/channel mismatch (interface={iface}, channel={channels})"
        )
    newline = "\r\n" if lines[indices[0]].endswith("\r\n") else "\n"
    lines[indices[0]] = f"ssid={ssid}{newline}"
    return "".join(lines)


def updated_dns(original, domain, ip):
    if original.count(START_MARKER) != original.count(END_MARKER):
        raise ApplyError("Incomplete managed DNS record block")
    if original.count(START_MARKER) > 1:
        raise ApplyError("Multiple managed DNS blocks detected")

    without_managed = original
    if START_MARKER in original:
        begin = original.index(START_MARKER)
        end = original.index(END_MARKER) + len(END_MARKER)
        without_managed = original[:begin].rstrip("\n") + "\n" + original[end:].lstrip("\n")

    # Any pre-existing record outside our block must be left in place.
    # A different target would be ambiguous, so fail rather than overwrite it.
    same_record_exists = False
    for line in without_managed.splitlines():
        value = line.strip()
        if value.startswith("#"):
            continue
        if value.startswith("host-record="):
            record = value.partition("=")[2].split(",")
            if record and record[0].lower() == domain:
                if len(record) < 2 or record[1] != ip:
                    raise ApplyError(f"Conflicting existing host-record for {domain}")
                same_record_exists = True
        if value.startswith("address=/") and value.partition("/")[2].split("/")[0].lower() == domain:
            raise ApplyError(f"Conflicting address record for {domain}")
    if same_record_exists:
        return without_managed
    return (
        without_managed.rstrip("\n") + "\n\n" +
        START_MARKER + "\n" +
        f"host-record={domain},{ip}\n" +
        END_MARKER + "\n"
    )


def atomic_replace(path, contents):
    st = path.stat()
    fd, tmpname = tempfile.mkstemp(prefix=".techworld-update-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(tmpname, st.st_uid, st.st_gid)
        os.chmod(tmpname, st.st_mode & 0o7777)
        os.replace(tmpname, path)
    finally:
        if os.path.exists(tmpname):
            os.unlink(tmpname)


def apply_existing(plan, runner=command):
    """Apply approved SSID/DNS changes transactionally with rollback."""
    existing_dns = verify_target(plan, runner)
    original_ssid = HOSTAPD.read_text()
    new_ssid = updated_ssid(
        original_ssid, plan["wireless"]["ssid"], plan["wireless"]["channel"]
    )
    ip = str(ipaddress.IPv4Interface(plan["portal"]["gateway"]).ip)
    new_dns = updated_dns(existing_dns, plan["portal"]["domain"], ip)

    to_change = []
    if new_ssid != original_ssid:
        to_change.append((HOSTAPD, original_ssid, new_ssid, "techworld-hostapd"))
    if new_dns != existing_dns:
        to_change.append((DNSMASQ, existing_dns, new_dns, "techworld-dhcp"))
    if not to_change:
        return {"changed": False, "message": "Requested settings already active"}

    # A DNS configuration test does not start a second DNS server.
    if new_dns != existing_dns:
        fd, staging = tempfile.mkstemp(prefix=".techworld-dns-test-", dir=DNSMASQ.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(new_dns)
            runner(["dnsmasq", "--test", "--conf-file=" + staging])
        finally:
            Path(staging).unlink(missing_ok=True)

    # Exact originals are preserved for both rollback and operator recovery.
    backup_dir = BACKUPS / datetime.now(timezone.utc).strftime("apply-%Y%m%dT%H%M%S%fZ")
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    for path, _, _, _ in to_change:
        shutil.copy2(path, backup_dir / path.name)

    changed = []
    try:
        # Apply the complete file set before restarting the two child services.
        for path, _, replacement, service in to_change:
            atomic_replace(path, replacement)
            changed.append((path, service))
        for _, _, _, service in to_change:
            runner(["systemctl", "restart", service])
        for service in ("techworld-hotspot", "techworld-hostapd", "techworld-dhcp", "opennds"):
            if runner(["systemctl", "is-active", service]).strip() != "active":
                raise ApplyError(f"{service} failed health verification")
    except Exception as exc:
        restore_errors = []
        for path, service in reversed(changed):
            try:
                shutil.copy2(backup_dir / path.name, path)
            except OSError as err:
                restore_errors.append(f"{path}: {err}")
        for _, service in reversed(changed):
            try:
                runner(["systemctl", "restart", service])
            except ApplyError as err:
                restore_errors.append(str(err))
        raise ApplyError(
            f"Update failed: {exc}. Rollback attempted. "
            + (("Rollback errors: " + "; ".join(restore_errors)) if restore_errors
               else "Original settings restored.")
        ) from exc

    return {
        "changed": True,
        "backup_directory": str(backup_dir),
        "services_restarted": [item[3] for item in to_change],
        "note": "SSID and local DNS alias updated; Laravel/Caddy portal is not yet installed",
    }
