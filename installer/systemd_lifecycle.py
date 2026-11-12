"""Read-only systemd lifecycle policy for a future supervised deployment.

Never treat source files as proof of the *installed* units: systemd drop-ins
and ExecStopPost may override them. The controller must inspect the merged
effective unit configuration before authorizing any service stop.
"""
import re

from installer.linux_adapters import UNITS


class LifecycleError(RuntimeError):
    pass


# Stop downstream consumers before the AP. This is a proposed policy,
# not an executable stop sequence.
STOP_ORDER = (
    "techworld-hotspot", "opennds", "techworld-hostapd",
    "techworld-dhcp", "techworld-isolation", "techworld-nat",
    "techworld-ap",
)

assert set(STOP_ORDER) == UNITS


def _directives(text):
    """Parse source text conservatively; fail on lines we cannot understand."""
    if not isinstance(text, str) or not text.strip():
        raise LifecycleError("Missing unit configuration")
    section = None
    fields = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            if section not in ("Unit", "Service", "Install"):
                raise LifecycleError("Unknown unit section")
            continue
        if line.endswith("\\"):
            raise LifecycleError("Unresolved line continuation")
        if "=" not in line or section is None:
            raise LifecycleError("Malformed unit configuration")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", key):
            raise LifecycleError("Malformed unit directive")
        fields.setdefault((section, key), []).append(value.strip())
    if not any(k[0] == "Service" for k in fields):
        raise LifecycleError("Missing Service section")
    return fields


def review_unit_sources(units):
    """Return blockers; never mark the repository production-ready.

    A complete seven-unit mapping is required; extra units are rejected.
    This reviews repository sources only, NOT loaded systemd configuration.
    """
    if not isinstance(units, dict) or set(units) != UNITS:
        raise LifecycleError("All seven exact Techworld unit sources required")
    blockers = []
    for unit in STOP_ORDER:
        fields = _directives(units[unit])
        for directive in ("ExecStart", "ExecStartPre", "ExecStartPost",
                          "ExecStop", "ExecStopPost"):
            for value in fields.get(("Service", directive), ()):
                # Any AP cleanup command is unresolved, including when
                # hidden behind a helper script or sh -c. A known safe
                # replacement must pass a separate privileged review.
                if unit == "techworld-ap" and directive in ("ExecStop", "ExecStopPost"):
                    blockers.append(f"{unit}: stop path unverified ({directive})")
                if "techworld-ap-cleanup" in value or "iw dev ap0 del" in value:
                    blockers.append(f"{unit}: name-based cleanup reference")
        if unit == "techworld-ap":
            for val in fields.get(("Service", "ExecStart"), ()):
                if "techworld-ap-prepare" in val:
                    blockers.append(f"{unit}: legacy prepare script")
        if unit == "techworld-hotspot":
            for val in fields.get(("Install", "WantedBy"), ()):
                if "multi-user.target" in val:
                    blockers.append("techworld-hotspot: boot activation possible")
        if unit == "opennds":
            for val in fields.get(("Install", "WantedBy"), ()):
                if "multi-user.target" in val:
                    blockers.append("opennds: independently enableable")
    return {
        "source_safe_to_deploy": False,
        "installed_units_verified": False,
        "stop_order_preview": list(STOP_ORDER),
        "blockers": sorted(set(blockers)),
    }


def load_repository_units(root):
    """Read-only scan of checked-in unit sources."""
    from pathlib import Path
    base = Path(root) / "systemd"
    return review_unit_sources({
        unit: (base / (unit + ".service")).read_text(encoding="utf-8")
        for unit in STOP_ORDER
    })


def stop_plan(states, *, installed_units_verified=False):
    """Never produce a live stop plan from unverified installed units.

    The loaded installed units must be reviewed separately, including
    drop-ins, and a privileged stop-path audit is not implemented.
    """
    if not isinstance(states, dict) or set(states) != UNITS:
        raise LifecycleError("Incomplete service state inventory")
    if not installed_units_verified:
        raise LifecycleError("Installed systemd units and overrides not verified")
    if any(value not in ("inactive", "failed", "active", "activating",
                         "deactivating") for value in states.values()):
        raise LifecycleError("Unverifiable service state")
    # Even with externally asserted verification, avoid handing out an
    # executable stop plan until its validation protocol exists.
    raise LifecycleError("Live service stop plan not implemented")
