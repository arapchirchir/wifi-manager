"""Ownership-checked cleanup executor, NOT yet wired to the live hotspot.

The default action is a read-only plan. The injection-friendly execute function
is for offline simulations until the installer controls the runtime receipt.
"""
import json
import subprocess

from installer.ownership_receipt import read_receipt
from installer.resource_ownership import cleanup_plan


class CleanupError(RuntimeError):
    pass


def shell_read(args):
    proc = subprocess.run(args, capture_output=True, text=True, timeout=8)
    if proc.returncode:
        raise CleanupError(proc.stderr.strip() or "Interface inspection failed")
    return proc.stdout


def observe(names, reader=shell_read):
    """Collect current ifindices and kinds from iproute2 and iw, read-only."""
    raw = json.loads(reader(["ip", "-j", "-d", "link", "show"]))
    if not isinstance(raw, list) or not all(
        isinstance(item, dict)
        and isinstance(item.get("ifname"), str)
        and item["ifname"]
        and type(item.get("ifindex")) is int
        and item["ifindex"] > 0
        for item in raw
    ):
        raise CleanupError("Invalid or incomplete iproute2 link report")
    names_seen = [item["ifname"] for item in raw]
    indices_seen = [item["ifindex"] for item in raw]
    if len(names_seen) != len(set(names_seen)) or len(indices_seen) != len(set(indices_seen)):
        raise CleanupError("Duplicate interface identity in link report")
    by_name = {item["ifname"]: item for item in raw}
    seen = {}
    for name in names:
        if name not in by_name:
            continue
        item = by_name[name]
        index = item.get("ifindex")
        linkinfo = item.get("linkinfo")
        if linkinfo is not None and not isinstance(linkinfo, dict):
            raise CleanupError("Invalid link kind report")
        kind = (linkinfo or {}).get("info_kind")
        if kind == "bridge":
            seen[name] = {"ifindex": index, "kind": "bridge"}
            continue
        # Verify AP type independently, do not trust the name or link kind.
        detail = reader(["iw", "dev", name, "info"])
        is_ap = any(line.strip() == "type AP" for line in detail.splitlines())
        seen[name] = {"ifindex": index, "kind": "AP" if is_ap else "unverified"}
    return seen



def bridge_members(bridge, reader=shell_read):
    """Fail closed when a bridge has attached links, including unrelated ones.

    The AP must be removed first. Linux iproute2 reports bridge membership
    through each link's 'master' field; an unknown response never permits
    deleting the bridge.
    """
    raw = json.loads(reader(["ip", "-j", "-d", "link", "show"]))
    if not isinstance(raw, list):
        raise CleanupError("Invalid link listing during bridge membership check")
    if not all(
        isinstance(item, dict)
        and isinstance(item.get("ifname"), str)
        and item["ifname"]
        and type(item.get("ifindex")) is int
        and item["ifindex"] > 0
        for item in raw
    ):
        raise CleanupError("Incomplete link listing during bridge membership check")
    names = [item["ifname"] for item in raw]
    indices = [item["ifindex"] for item in raw]
    if len(set(names)) != len(names) or len(set(indices)) != len(indices):
        raise CleanupError("Ambiguous link listing during bridge membership check")
    matches = [item for item in raw if item["ifname"] == bridge]
    if len(matches) != 1:
        raise CleanupError("Bridge identity absent during membership check")
    return [item["ifname"] for item in raw if item.get("master") == bridge]


def safe_cleanup(receipt_path, *, execute=False, reader=shell_read, mutator=None):
    """Refuse any deletion without a valid receipt and exact live identity.

    Even execute=True requires a caller-supplied mutator. No production
    mutator exists here yet; this cannot change interfaces as shipped.
    """
    inventory = read_receipt(receipt_path)
    names = [item["name"] for item in inventory["interfaces"]]
    initial = cleanup_plan(inventory, observe(names, reader))
    result = {"executed": False, "plan": initial, "deleted": [], "errors": []}
    if initial["refuse"]:
        result["errors"].extend(initial["refuse"])
        return result
    if not execute:
        return result
    if mutator is None:
        result["errors"].append("Execution unavailable: no approved cleanup executor")
        return result

    # Reobserve immediately before every removal. If anything changes,
    # abandon the transaction instead of deleting a reused interface name.
    for name, kind, index in initial["remove"]:
        latest = cleanup_plan(inventory, observe(names, reader))
        if latest["refuse"] or (name, kind, index) not in latest["remove"]:
            result["errors"].append(f"Interface identity changed before removal: {name}")
            break
        if kind == "bridge":
            # Do not remove a bridge until the recorded AP is absent.
            ap_names = [i["name"] for i in inventory["interfaces"] if i["kind"] == "ap"]
            present = observe(ap_names, reader)
            if any(ap in present for ap in ap_names):
                result["errors"].append("Recorded AP still present; retaining bridge")
                break
        if kind == "bridge":
            try:
                members = bridge_members(name, reader)
            except (OSError, ValueError, TypeError, RuntimeError, CleanupError) as exc:
                result["errors"].append(f"Cannot verify bridge membership: {exc}")
                break
            if members:
                result["errors"].append(
                    f"Bridge {name} still has attached interfaces: {members}"
                )
                break
        mutator(name, kind, index)
        result["deleted"].append(name)
    result["executed"] = bool(result["deleted"])
    return result
