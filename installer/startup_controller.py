"""Coordinated offline startup/recovery engine for Techworld-WiFi.

No production adapter or service runner is shipped here. All mutations are
injected by the test harness. The controller rejects existing services and
orphan network resources, rechecks the upstream, and tears down only the
resources created by this attempt. A caller must still hold a process lock,
persist a crash-recovery journal, and verify the installer ownership manifest.
"""
from installer import network_transaction, ap_transaction, hostapd_transaction


class StartupError(RuntimeError):
    pass


TECHWORLD_UNITS = (
    "techworld-hotspot", "opennds", "techworld-hostapd", "techworld-dhcp",
    "techworld-isolation", "techworld-nat", "techworld-ap",
)


def startup(adapter, services, *, receipt_dir, hostapd_path, channel,
            upstream_check, post_check):
    """Run a supervised simulation; never touch external host services.

    services.state(unit) returns 'inactive' or another state.
    services.start()/stop() work only with Techworld units and are injected.
    upstream_check() returns an immutable snapshot; post_check() returns bool.
    """
    initial = {unit: services.state(unit) for unit in TECHWORLD_UNITS}
    if any(state != "inactive" for state in initial.values()):
        raise StartupError("Techworld stack is not fully inactive; refusing adoption")

    # Reject existing resources before any service or config mutation.
    for name in ("ap0", "br-techworld"):
        if adapter.inspect(name) is not None:
            raise StartupError(f"Unowned interface exists: {name}")

    before = upstream_check()
    if before is None:
        raise StartupError("Upstream not verified before startup")
    if not isinstance(before, tuple) or len(before) < 2:
        raise StartupError("Upstream snapshot must be an immutable identity tuple")
    if before[1] != channel:
        raise StartupError("Desired AP channel disagrees with verified upstream")

    original = hostapd_transaction._read_regular(hostapd_path)[0]
    setup = None
    start_attempted = False
    errors = []
    try:
        setup = network_transaction.prepare_network(
            adapter, receipt_dir=receipt_dir, hostapd_path=hostapd_path,
            channel=channel, upstream_check=upstream_check,
        )
        if upstream_check() != before:
            raise StartupError("Upstream changed before service startup")
        start_attempted = True
        services.start("techworld-hotspot")
        if not post_check():
            raise StartupError("Post-start verification failed")
        if upstream_check() != before:
            raise StartupError("Upstream changed during post-start verification")
        return {"started": True, "upstream": before,
                "services": {"techworld-hotspot": services.state("techworld-hotspot")},
                "restart_safe": False}
    except Exception as exc:
        # If start may have partially run, stop the Techworld parent first,
        # then only explicitly enumerated owned children. Never stop unrelated
        # services or network managers.
        if start_attempted:
            for unit in TECHWORLD_UNITS:
                try:
                    if unit == "techworld-hotspot" or services.state(unit) not in (
                        "inactive", "failed"
                    ):
                        services.stop(unit)
                except Exception as stop_exc:
                    errors.append(f"Cannot stop {unit}: {stop_exc}")
        try:
            residual = {unit: services.state(unit) for unit in TECHWORLD_UNITS
                        if services.state(unit) not in ("inactive", "failed")}
            if residual:
                errors.append(f"Techworld services still active: {residual}")
        except Exception as state_exc:
            errors.append(f"Cannot verify service shutdown: {state_exc}")

        # Do not delete interfaces while Techworld services remain running.
        if not any("services still active" in item or "Cannot verify service" in item
                   or item.startswith("Cannot stop") for item in errors):
            try:
                errors.extend(ap_transaction.rollback(adapter, receipt_dir))
            except Exception as rollback_exc:
                errors.append(f"Interface cleanup unavailable: {rollback_exc}")
        else:
            errors.append("Interface cleanup postponed; service state uncertain")

        # Restore config only when it can be proven we installed its current
        # contents and original bytes are known. Do not overwrite other edits.
        if setup is not None and setup["config_modified"]:
            try:
                changed = hostapd_transaction.render_channel(original, channel)
                if changed != hostapd_transaction._read_regular(hostapd_path)[0]:
                    raise StartupError("Hostapd changed externally; not restoring")
                info = hostapd_transaction._read_regular(hostapd_path)[1]
                hostapd_transaction._replace_bytes(hostapd_path, original, info)
            except Exception as config_exc:
                errors.append(f"Cannot restore hostapd: {config_exc}")

        if errors:
            raise StartupError(f"Startup failed: {exc}; recovery incomplete: {errors}") from exc
        raise StartupError(f"Startup failed and recovery completed: {exc}") from exc
