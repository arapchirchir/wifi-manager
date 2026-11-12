"""Read-only radio candidate evaluation, no AP activation or channel changes."""
import re

from installer.auto_network import supports_sta_ap


class RadioError(ValueError):
    pass


def parse_radios(iw_dev):
    """List managed interfaces by PHY, and all observed PHY numbers."""
    current = None
    radios = {}
    iface = None
    for line in iw_dev.splitlines():
        phy = re.match(r"^\s*phy#(\d+)\s*$", line)
        if phy:
            current = "phy" + phy.group(1)
            radios.setdefault(current, {"managed": []})
            iface = None
            continue
        item = re.match(r"^\s*Interface\s+(\S+)\s*$", line)
        if item:
            iface = item.group(1)
            continue
        if current and iface and re.match(r"^\s*type\s+managed\s*$", line):
            if iface not in radios[current]["managed"]:
                radios[current]["managed"].append(iface)
    return radios


def allowed_legacy_channels(phy_info):
    """Conservative 2.4GHz legacy channels, refusing disabled/no-IR entries.

    This is deliberately stricter than a full regulatory compliance check.
    The production installer must also check regulatory domain and rfkill.
    """
    channels = set()
    for line in phy_info.splitlines():
        match = re.search(r"\*\s+(\d+)\s+MHz\s+\[(\d+)\]", line)
        if not match:
            continue
        freq, channel = int(match.group(1)), int(match.group(2))
        if not (2412 <= freq <= 2462 and 1 <= channel <= 11):
            continue
        if re.search(r"\bdisabled\b|\bno IR\b|\bno-IR\b", line, re.I):
            continue
        channels.add(channel)
    return sorted(channels)


def choose_radio(radios, selected, phy_infos, *, preferred=None):
    """Choose a unique viable AP PHY and channel; return reasons otherwise.

    selected is the selected route from uplink_selection.select_route.
    For same-PHY Wi-Fi STA, the AP must match its 2.4GHz channel and PHY
    must advertise concurrent AP+STA. For Ethernet or an independent radio,
    reject ambiguity rather than picking an arbitrary adapter.
    """
    if not radios:
        raise RadioError("No Wi-Fi radio detected for hotspot AP")
    if preferred is not None and preferred not in radios:
        raise RadioError("Requested AP radio does not exist")
    candidates = [preferred] if preferred else sorted(radios)
    viable = []
    for phy in candidates:
        info = phy_infos.get(phy, "")
        available = allowed_legacy_channels(info)
        if not available:
            continue
        is_shared = selected["kind"] == "wifi" and selected.get("phy") == phy
        if is_shared:
            if not supports_sta_ap(info):
                continue
            channel = selected.get("channel")
            if channel not in available:
                continue
            reason = "shared-radio-wifi"
        else:
            # AP mode advertised; do not require STA+AP concurrency for an
            # Ethernet WAN on an otherwise unused wireless PHY.
            modes = info.split("Supported interface modes:", 1)
            if len(modes) != 2 or not re.search(
                r"(?m)^\s*\*\s+AP\s*$",
                modes[1].split("valid interface combinations:", 1)[0]
            ):
                continue
            if radios[phy]["managed"]:
                # Managed interface on a distinct PHY may already be in use.
                # Refuse to alter its role without independent verification.
                continue
            channel = 1 if 1 in available else available[0]
            reason = "independent-ap-radio"
        viable.append({"phy": phy, "channel": channel, "reason": reason,
                       "regulatory_verified": False})
    if not viable:
        raise RadioError("No validated legacy 2.4GHz AP radio/channel available")
    if len(viable) != 1:
        raise RadioError("Multiple eligible AP radios; specify one explicitly")
    return viable[0]
