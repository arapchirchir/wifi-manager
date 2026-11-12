"""Read-only, fail-closed WAN uplink selection for Techworld-WiFi.

This is a discovery/decision component, not a live hotspot reconfiguration
engine. It does not invoke NetworkManager activation or change a route.
A default route and connected state do NOT prove Internet reachability.
"""
import ipaddress
import json
import re
import subprocess


class SelectionError(ValueError):
    pass


def run(args):
    proc = subprocess.run(args, capture_output=True, text=True, timeout=8)
    if proc.returncode:
        raise SelectionError(f"{args[0]} inspection failed: {proc.stderr.strip()}")
    return proc.stdout


def _connected(state):
    return bool(re.match(r"^100(?:\s*\(connected\))?", state.strip()))


def select_route(routes, devices, associations, *, ap_radio=None):
    """Pick the lowest-metric verified active WAN route; prefer Ethernet on ties.

    devices maps interface to {"type": "ethernet"|"wifi", "connected": bool}.
    associations maps Wi-Fi interface to {"ssid", "channel", "phy"}.
    A same-radio Wi-Fi WAN must use the same AP channel; Ethernet may use a
    separate Wi-Fi AP radio. Equal-priority conflicting WANs are ambiguous.
    """
    candidates = []
    for route in routes:
        if route.get("dst") != "default":
            continue
        name = route.get("dev")
        device = devices.get(name, {})
        kind = device.get("type")
        if kind not in ("wifi", "ethernet") or not device.get("connected"):
            continue
        gateway = route.get("gateway")
        try:
            ipaddress.IPv4Address(gateway)
        except (ValueError, TypeError):
            continue
        metric = route.get("metric", 0)
        if type(metric) is not int or metric < 0:
            continue
        info = {"interface": name, "kind": kind, "gateway": gateway,
                "metric": metric, "internet_verified": False}
        if kind == "wifi":
            linked = associations.get(name, {})
            if not linked.get("ssid") or type(linked.get("channel")) is not int:
                continue
            if not 1 <= linked["channel"] <= 196:
                continue
            info.update({"ssid": linked["ssid"], "channel": linked["channel"],
                         "phy": linked.get("phy")})
            if ap_radio is not None and linked.get("phy") == ap_radio:
                if linked["channel"] > 11:
                    # The current legacy AP configuration supports 2.4 GHz only.
                    continue
                info["ap_channel"] = linked["channel"]
                info["channel_source"] = "shared-radio-wifi"
            else:
                info["ap_channel"] = None
                info["channel_source"] = "independent-radio-requires-validation"
        else:
            info.update({"ssid": None, "channel": None, "phy": None,
                         "ap_channel": None,
                         "channel_source": "ethernet-requires-ap-radio-validation"})
        candidates.append(info)
    if not candidates:
        raise SelectionError("No connected Wi-Fi/Ethernet default route with a valid gateway")
    candidates.sort(key=lambda item: (item["metric"], item["kind"] != "ethernet"))
    best = candidates[0]
    if any(item["metric"] == best["metric"] and item["kind"] == best["kind"]
           and (item["interface"], item["gateway"]) !=
           (best["interface"], best["gateway"]) for item in candidates[1:]):
        raise SelectionError("Ambiguous equal-priority WAN default routes")
    return {"selected": best, "candidates": candidates,
            "requires_internet_probe": True,
            "restart_safe": False}


def inspect(*, reader=run, ap_radio=None):
    """Inspect current routing and NetworkManager state without writes."""
    try:
        routes = json.loads(reader(["ip", "-j", "-4", "route", "show", "default"]))
        if not isinstance(routes, list):
            raise ValueError("Routes must be a JSON array")
        rows = reader(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"])
        devices = {}
        for row in rows.splitlines():
            # NetworkManager's terse format escapes literal colon in names.
            parts = re.split(r"(?<!\\):", row, maxsplit=2)
            if len(parts) != 3:
                continue
            name, kind, state = (part.replace(r"\:", ":") for part in parts)
            normalized = {"wifi": "wifi", "ethernet": "ethernet"}.get(kind)
            if normalized:
                devices[name] = {"type": normalized, "connected": state == "connected"}
        associations = {}
        for name, device in devices.items():
            if device["type"] != "wifi" or not device["connected"]:
                continue
            link = reader(["iw", "dev", name, "link"])
            info = reader(["iw", "dev", name, "info"])
            match = re.search(r"(?m)^\s*SSID:\s*(.+?)\s*$", link)
            channel = re.search(r"(?m)^\s*channel\s+(\d+)\b", info)
            phy = re.search(r"(?m)^\s*wiphy\s+(\d+)\b", info)
            if re.search(r"(?m)^Connected to [0-9a-fA-F:]{17}\b", link) and match and channel:
                associations[name] = {"ssid": match.group(1),
                                      "channel": int(channel.group(1)),
                                      "phy": "phy" + phy.group(1) if phy else None}
        return select_route(routes, devices, associations, ap_radio=ap_radio)
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError) as exc:
        raise SelectionError(f"WAN selection unavailable: {exc}") from exc
