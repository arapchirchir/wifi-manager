"""Fail-closed read-only recovery reconciliation for reserved Techworld interfaces.

Compares durable creation intents, post-creation ifindex receipts, the startup
journal and a fresh observed network inventory. No result authorizes cleanup,
adoption, restart, or automatic removal of markers. All observations are
snapshots and can become stale immediately.
"""
from pathlib import Path

from installer.creation_intent import RESERVED, read_intent
from installer.ownership_receipt import read_receipt
from installer.recovery_journal import read_journal
from installer.owned_cleanup import observe, shell_read


class ReconciliationError(RuntimeError):
    pass


KINDS = {"ap": "AP", "bridge": "bridge"}


def _receipt(folder, name, kind):
    path = Path(folder) / (name + ".json")
    try:
        record = read_receipt(path)
    except FileNotFoundError:
        return None
    items = record["interfaces"]
    if (len(items) != 1 or items[0]["name"] != name or
            items[0]["kind"] != kind):
        raise ReconciliationError(
            f"Ownership receipt does not uniquely identify reserved interface {name}"
        )
    return items[0]


def reconcile(folder, *, reader):
    """Assess evidence under a caller-held setup lock; read-only.

    A supplied reader is mandatory. An unreliable, malformed or contradictory
    inventory raises; it never means that a missing interface is safe to adopt.
    No issued recommendation is executable.
    """
    if not callable(reader):
        raise TypeError("Explicit read-only network reader required")
    journal = read_journal(folder)
    live = observe(tuple(RESERVED), reader=reader)
    results = {}
    indices = []
    for name, kind in RESERVED.items():
        intent = read_intent(folder, name, kind)
        receipt = _receipt(folder, name, kind)
        current = live.get(name)
        if receipt is not None:
            indices.append(receipt["ifindex"])
        if current is not None:
            if (type(current.get("ifindex")) is not int or
                    current["ifindex"] <= 0):
                raise ReconciliationError(f"Unverified live identity: {name}")

        if current is None and intent is None and receipt is None:
            status = "no_record_no_interface"
        elif current is not None and intent is None and receipt is None:
            status = "unrecorded_live_interface"
        elif receipt is not None and intent is None:
            status = "receipt_without_intent"
        elif receipt is None and intent is not None:
            status = ("intent_without_receipt_live_interface" if current is not None
                      else "intent_without_receipt_interface_absent")
        elif current is None:
            status = "receipt_recorded_interface_absent"
        elif (current["ifindex"] != receipt["ifindex"]
              or current["kind"] != KINDS[kind]):
            status = "receipt_live_identity_mismatch"
        else:
            # This is a snapshot consistency check, NOT proof of ownership.
            status = "receipt_matches_live_snapshot"
        results[name] = {
            "status": status,
            "intent_present": intent is not None,
            "receipt_present": receipt is not None,
            "recorded_ifindex": receipt["ifindex"] if receipt else None,
            "observed": current,
        }

    if len(indices) != len(set(indices)):
        raise ReconciliationError("Duplicate recorded interface indices")

    return {
        "journal_state": journal["state"] if journal else "absent",
        "interfaces": results,
        "manual_review_required": (
            journal is not None or
            any(item["status"] != "no_record_no_interface" for item in results.values())
        ),
        "safe_to_restart": False,
        "automatic_cleanup_allowed": False,
        "ownership_proven": False,
        "note": "Read-only snapshot; never authorizes deletion, adoption or startup.",
    }
