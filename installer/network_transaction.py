"""One coordinated, offline-testable AP and hostapd preparation transaction.

This is NOT a live systemd installer. The supplied adapter controls all
interface operations. A caller must acquire an exclusive lock and ensure
network prerequisites; no production adapter is exposed here.
"""
from pathlib import Path

from installer import ap_transaction, hostapd_transaction


class SetupError(RuntimeError):
    pass


def prepare_network(adapter, *, receipt_dir, hostapd_path, channel,
                    upstream_check):
    """Verify upstream, update config, create AP, rollback both on failure.

    The upstream_check callable returns a snapshot identifier (SSID, channel,
    gateway, adapter) and must raise on an unhealthy connection. It is called
    again after interface creation; a changed snapshot fails the transaction.
    """
    snapshot = upstream_check()
    if snapshot is None:
        raise SetupError("No verified upstream snapshot")
    configuration = None
    prepared = False
    try:
        configuration = hostapd_transaction.apply_channel(hostapd_path, channel)
        result = ap_transaction.prepare(adapter, receipt_dir)
        prepared = True
        if upstream_check() != snapshot:
            raise SetupError("Upstream changed during AP creation")
        return {"upstream": snapshot, "interfaces": result,
                "config_modified": configuration["modified"]}
    except Exception as exc:
        failures = []
        # AP preparation already rolls back its own partial creation; calling
        # again also handles completion followed by an upstream change.
        try:
            failures.extend(ap_transaction.rollback(adapter, receipt_dir))
        except Exception as rollback_exc:
            failures.append(f"Interface rollback: {rollback_exc}")
        if configuration is not None:
            try:
                hostapd_transaction.rollback_channel(hostapd_path, configuration)
            except Exception as rollback_exc:
                failures.append(f"Hostapd rollback: {rollback_exc}")
        if failures:
            raise SetupError(f"Setup failed ({exc}); rollback incomplete: {failures}") from exc
        raise SetupError(f"Setup failed and rollback completed: {exc}") from exc
