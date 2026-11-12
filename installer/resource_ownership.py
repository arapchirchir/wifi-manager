"""Pure, fail-closed interface ownership decisions for Techworld-WiFi.

Planning only: no commands, file writes or interface manipulation. A future
supervised setup will store a runtime inventory of interfaces it created,
including ifindex and expected type, and use this logic before cleanup.
"""
import re

IFACE_RE = re.compile(r"^[a-zA-Z0-9_.:-]{1,15}$")
OWNED_TYPES = {"ap": "AP", "bridge": "bridge"}


def validate_inventory(inventory):
    """Validate a machine-readable creation record; raise on ambiguity."""
    if not isinstance(inventory, dict) or inventory.get("version") != 1:
        raise ValueError("Missing or unsupported Techworld ownership record")
    items = inventory.get("interfaces")
    if not isinstance(items, list) or not items:
        raise ValueError("Ownership record has no interfaces")
    names = set()
    indexes = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Malformed interface record")
        name = item.get("name")
        kind = item.get("kind")
        index = item.get("ifindex")
        if not isinstance(name, str) or not IFACE_RE.fullmatch(name) or name.startswith("-"):
            raise ValueError("Invalid recorded interface name")
        if kind not in OWNED_TYPES:
            raise ValueError("Unknown interface kind")
        if type(index) is not int or index <= 0:
            raise ValueError("Invalid recorded interface index")
        if name in names or index in indexes:
            raise ValueError("Duplicate interface name/index")
        names.add(name)
        indexes.add(index)
    return items


def cleanup_plan(inventory, observed):
    """Return ordered safe removals plus refusal reasons.

    observed maps name to {"ifindex": positive int, "kind": "AP"|"bridge"}.
    A missing interface needs no removal; a mismatch must never be deleted.
    Bridge removal follows AP removal. No heuristics or name-only deletion.
    """
    records = validate_inventory(inventory)
    if not isinstance(observed, dict):
        raise ValueError("Invalid observed interfaces")
    deletions = []
    refusals = []
    for record in records:
        name = record["name"]
        current = observed.get(name)
        if current is None:
            continue
        if not isinstance(current, dict) or (
            current.get("ifindex") != record["ifindex"]
        ) or current.get("kind") != OWNED_TYPES[record["kind"]]:
            refusals.append(f"Refusing to remove unverified interface {name}")
            continue
        deletions.append((name, record["kind"], record["ifindex"]))
    # Only remove the recorded bridge when its recorded AP can be safely
    # removed or is already absent; avoid tearing down a bridge on AP mismatch.
    if any(r["kind"] == "ap" and any(r["name"] in msg for msg in refusals)
           for r in records):
        deletions = [d for d in deletions if d[1] != "bridge"]
        refusals.append("Bridge retained because associated AP ownership is ambiguous")
    deletions.sort(key=lambda item: 0 if item[1] == "ap" else 1)
    return {"remove": deletions, "refuse": refusals}
