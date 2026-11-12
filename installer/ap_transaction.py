"""Transactional AP provisioning core, offline until installer integration.

Only this module manages the creation ledger. It creates a private receipt for
each interface immediately after verifying its type/index; failures invoke
ownership-checked rollback. Caller supplies an isolated execution adapter, so
no host networking is changed by importing this module.
"""
from pathlib import Path

from installer.ownership_receipt import write_new_receipt, read_receipt
from installer.owned_cleanup import safe_cleanup


class ProvisionError(RuntimeError):
    pass


INTERFACES = (("br-techworld", "bridge"), ("ap0", "ap"))


def prepare(adapter, receipt_dir):
    """Create and verify dedicated interfaces, with rollback on failure.

    adapter.inspect(name) -> None or {ifindex, kind}, adapter.create(name, kind),
    adapter.read(command) -> stdout, adapter.remove(name, kind, index).
    The caller must supply a privately owned mode-0700 receipt_dir, a lock
    covering concurrent runs, and independent upstream/config verification.
    """
    directory = Path(receipt_dir)
    receipts = [directory / (name + ".json") for name, _ in INTERFACES]
    if any(path.exists() or path.is_symlink() for path in receipts):
        raise ProvisionError("Stale or conflicting ownership receipt; refusing adoption")
    if any(adapter.inspect(name) is not None for name, _ in INTERFACES):
        raise ProvisionError("Reserved interface name already exists; refusing adoption")

    created = []
    try:
        for (name, kind), path in zip(INTERFACES, receipts):
            adapter.create(name, kind)
            # Only this transaction can have created the interface, because
            # name collision checks happened before create. Verify instantly.
            observed = adapter.inspect(name)
            wanted = "bridge" if kind == "bridge" else "AP"
            if not isinstance(observed, dict) or observed.get("kind") != wanted:
                raise ProvisionError(f"New interface failed type verification: {name}")
            index = observed.get("ifindex")
            if type(index) is not int or index <= 0:
                raise ProvisionError(f"New interface has no valid ifindex: {name}")
            created.append((name, kind, index))
            write_new_receipt(path, {
                "version": 1,
                "interfaces": [{"name": name, "kind": kind, "ifindex": index}],
            })
        return {"created": created, "receipts": [str(p) for p in receipts]}
    except Exception as exc:
        failures = rollback(adapter, directory)
        if failures:
            raise ProvisionError(
                f"AP preparation failed: {exc}; cleanup incomplete: {failures}"
            ) from exc
        raise ProvisionError(f"AP preparation failed and rolled back: {exc}") from exc


def rollback(adapter, receipt_dir):
    """Best-effort ownership-checked cleanup, AP first, then bridge.

    No missing receipt authorizes deletion. An orphan without a receipt is
    deliberately retained for manual investigation rather than name deletion.
    """
    directory = Path(receipt_dir)
    failures = []
    for name, _ in reversed(INTERFACES):
        path = directory / (name + ".json")
        if not path.exists() and not path.is_symlink():
            continue
        try:
            receipt = read_receipt(path)
            expected = receipt["interfaces"][0]
            current = adapter.inspect(name)
            if current is not None and (
                current.get("ifindex") != expected["ifindex"]
                or current.get("kind") != ("AP" if expected["kind"] == "ap" else "bridge")
            ):
                failures.append(f"Identity mismatch: {name}")
                continue
            # The ownership-aware planner re-inspects via the adapter.
            outcome = safe_cleanup(
                path, execute=True, reader=adapter.read, mutator=adapter.remove,
            )
            if outcome["errors"]:
                failures.extend(outcome["errors"])
                continue
            if adapter.inspect(name) is not None:
                failures.append(f"Interface not removed: {name}")
                continue
            path.unlink()
        except (OSError, ValueError, RuntimeError) as exc:
            failures.append(f"{name}: {exc}")
    return failures
