"""Read-only network discovery for the Techworld-WiFi installation preview.

Fail closed: an ambiguous uplink, unsupported radio, or overlapping subnet
must not become a default used by any future installation process.
"""
import ipaddress
import json
import re
import subprocess

CANDIDATES = (
    "10.77.77.1/24",
    "10.77.78.1/24",
    "10.93.77.1/24",
    "172.30.77.1/24",
    "192.168.77.1/24",
)


class DiscoveryError(ValueError):
    pass


def run_readonly(args):
    try:
        proc = subprocess.run(
            args, text=True, capture_output=True, check=False, timeout=8
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DiscoveryError(f"Cannot inspect network using {args[0]}: {exc}") from exc
    if proc.returncode:
        raise DiscoveryError(
            f"Cannot inspect network using {args[0]}: "
            f"{proc.stderr.strip() or 'command failed'}"
        )
    return proc.stdout


def parse_managed_interfaces(iw_output):
    """Map managed interfaces to their physical radio numbers."""
    current_phy, current_iface = None, None
    managed = {}
    for line in iw_output.splitlines():
        phy = re.search(r"^\s*phy#(\d+)\s*$", line)
        iface = re.search(r"^\s*Interface\s+(\S+)\s*$", line)
        if phy:
            current_phy, current_iface = phy.group(1), None
        elif iface:
            current_iface = iface.group(1)
        elif current_phy and current_iface and re.search(r"^\s*type\s+managed\s*$", line):
            managed[current_iface] = current_phy
    return managed


def supports_sta_ap(phy_info):
    if not re.search(r"Supported interface modes:[\s\S]*?\*\s+AP\b", phy_info):
        return False
    # A station+AP combination must be advertised by the same radio.
    # This is necessary but not sufficient: the channel must also be usable.
    for line in phy_info.splitlines():
        if ("#{" in line and "managed" in line and
                re.search(r"\bAP\b", line) and "total" in line):
            match = re.search(r"total\s*<=\s*(\d+)", line)
            if match and int(match.group(1)) >= 2:
                return True
    return False


def parse_json_output(args, runner):
    try:
        result = json.loads(runner(args))
        if not isinstance(result, list):
            raise ValueError("expected a JSON list")
        return result
    except (ValueError, TypeError) as exc:
        raise DiscoveryError(f"Cannot parse {args[0]} network data: {exc}") from exc


def active_uplink(runner=run_readonly):
    managed = parse_managed_interfaces(runner(["iw", "dev"]))
    routes = parse_json_output(["ip", "-j", "-4", "route", "show", "default"], runner)
    active = [route.get("dev") for route in routes if route.get("dev") in managed]
    if len(set(active)) != 1:
        raise DiscoveryError(
            "Cannot safely detect a single active Wi-Fi uplink with a default IPv4 route"
        )
    uplink = active[0]
    phy = managed[uplink]
    info = runner(["iw", "dev", uplink, "info"])
    match = re.search(r"\bchannel\s+(\d+)\b", info)
    if not match:
        raise DiscoveryError("Active Wi-Fi channel is unknown; verify upstream association")
    channel = int(match.group(1))
    phy_info = runner(["iw", "phy", "phy" + phy, "info"])
    if not supports_sta_ap(phy_info):
        raise DiscoveryError(
            "Radio does not advertise concurrent managed+AP interfaces; "
            "use a compatible second Wi-Fi adapter"
        )
    return {"uplink": uplink, "channel": channel, "phy": "phy" + phy}


def used_networks(runner=run_readonly):
    """Read the system routing and interface inventories, including Docker/VPN."""
    occupied = []
    routes = parse_json_output(
        ["ip", "-j", "-4", "route", "show", "table", "all"], runner
    )
    addresses = parse_json_output(["ip", "-j", "-4", "address", "show"], runner)
    for route in routes:
        dest = route.get("dst")
        if not dest or dest == "default":
            continue
        try:
            occupied.append((
                ipaddress.ip_network(dest, strict=False),
                route.get("dev"),
            ))
        except ValueError:
            continue
    bridge_addresses = []
    for item in addresses:
        device = item.get("ifname")
        for addr in item.get("addr_info", []):
            if addr.get("family") != "inet":
                continue
            try:
                iface = ipaddress.IPv4Interface(
                    f"{addr['local']}/{addr['prefixlen']}"
                )
            except (ValueError, KeyError):
                continue
            occupied.append((iface.network, device))
            if device == "br-techworld":
                bridge_addresses.append(iface)
    return occupied, bridge_addresses


def conflicting_network(candidate, occupied, allow_bridge=False):
    subnet = ipaddress.ip_interface(candidate).network
    return [
        f"{network} ({device or 'unknown'})"
        for network, device in occupied
        if network.overlaps(subnet)
        and not (allow_bridge and device == "br-techworld")
    ]


def auto_pool(gateway):
    iface = ipaddress.IPv4Interface(gateway)
    network = iface.network
    # Only generate a bounded pool. This installer currently uses /24 for
    # automatic subnet selection, keeping consistent client addressing.
    if network.prefixlen != 24:
        raise DiscoveryError("Automatic DHCP pool generation currently requires /24")
    base = int(network.network_address)
    candidates = ((50, 200), (101, 220), (2, 100), (150, 250))
    for low, high in candidates:
        start, end = ipaddress.IPv4Address(base + low), ipaddress.IPv4Address(base + high)
        if not (start <= iface.ip <= end):
            return str(start), str(end)
    raise DiscoveryError("No DHCP range available outside gateway address")


def discover(preflight_status, runner=run_readonly):
    uplink_info = active_uplink(runner)
    occupied, bridge_addresses = used_networks(runner)
    preserve_existing = preflight_status in ("adoption_required", "recorded_existing")
    current_gateway = None

    if preserve_existing:
        for address in bridge_addresses:
            if address.network.prefixlen == 24:
                conflicts = conflicting_network(
                    str(address), occupied, allow_bridge=True
                )
                if conflicts:
                    raise DiscoveryError(
                        "Existing hotspot gateway overlaps another interface: "
                        + ", ".join(conflicts)
                    )
                current_gateway = str(address)
                break

    if current_gateway:
        gateway = current_gateway
        source = "existing Techworld bridge (preserved)"
    else:
        gateway = next(
            (candidate for candidate in CANDIDATES
             if not conflicting_network(candidate, occupied)), None
        )
        if gateway is None:
            raise DiscoveryError(
                "All candidate private hotspot subnets overlap existing routes; "
                "configure an unused subnet manually after reviewing routes"
            )
        source = "automatically selected unused private subnet"

    dhcp_start, dhcp_end = auto_pool(gateway)
    return {
        **uplink_info,
        "gateway": gateway,
        "dhcp_start": dhcp_start,
        "dhcp_end": dhcp_end,
        "source": source,
        "occupied_networks": occupied,
        "preserve_existing": bool(current_gateway),
    }
