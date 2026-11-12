"""Read-only effective systemd unit inspection.

Checks *loaded* unit properties, not just checked-in .service files.
An injected executor is required and no mutation command is defined.
This is a blocker report, never production approval: systemd commands and
helper script contents still need independent human review.
"""
import re

from installer.systemd_lifecycle import STOP_ORDER, LifecycleError


PROPERTIES = (
    "Id", "LoadState", "ActiveState", "FragmentPath", "DropInPaths",
    "ExecStart", "ExecStartPre", "ExecStartPost", "ExecStop",
    "ExecStopPost", "Requires", "Wants", "After", "Before",
)
COMMAND = ("systemctl", "show", "--no-pager", "--all")


def _parse(text):
    if not isinstance(text, str):
        raise LifecycleError("Invalid systemd report")
    properties = {}
    for raw in text.splitlines():
        if "=" not in raw:
            raise LifecycleError("Malformed effective unit property")
        name, value = raw.split("=", 1)
        if name not in PROPERTIES or name in properties:
            raise LifecycleError("Unknown or duplicate effective unit property")
        properties[name] = value
    if set(properties) != set(PROPERTIES):
        raise LifecycleError("Incomplete effective unit properties")
    return properties


def _blockers(unit, properties):
    findings = []
    if properties["Id"] != unit + ".service":
        findings.append("Loaded unit identity mismatch")
    if properties["LoadState"] != "loaded":
        findings.append("Unit is not loaded")
    if properties["ActiveState"] not in (
        "active", "inactive", "failed", "activating", "deactivating",
        "reloading", "maintenance"
    ):
        findings.append("Unexpected active state")
    if not properties["FragmentPath"].startswith(("/etc/systemd/system/", "/usr/lib/systemd/system/", "/lib/systemd/system/")):
        findings.append("Untrusted or missing unit fragment")
    # Any drop-in requires a separate source review. This catches unseen
    # ExecStopPost overrides which a repository-only audit cannot see.
    if properties["DropInPaths"]:
        findings.append("Installed unit has drop-ins requiring inspection")
    for field in ("ExecStart", "ExecStartPre", "ExecStartPost",
                  "ExecStop", "ExecStopPost"):
        value = properties[field]
        if re.search(r"(?:techworld-ap-prepare|techworld-ap-cleanup|\biw\s+dev\s+ap0\s+del\b)", value):
            findings.append(f"{field} references legacy AP operation")
        if unit == "techworld-ap" and value and field in ("ExecStop", "ExecStopPost"):
            findings.append(f"{field} can run AP cleanup without verified ownership")
    if unit == "techworld-ap" and not properties["ExecStart"]:
        findings.append("Missing AP startup command")
    return findings


def inspect_effective_units(execute):
    """Issue read-only systemctl show commands through an injected executor.

    The returned assessment *always* requires human review and NEVER permits
    startup/shutdown. subprocess, shell and systemd mutation are not used.
    """
    if not callable(execute):
        raise TypeError("Explicit read-only executor required")
    result = {}
    for unit in STOP_ORDER:
        args = list(COMMAND) + sum((["-p", prop] for prop in PROPERTIES), []) + [unit + ".service"]
        report = _parse(execute(args))
        result[unit] = {
            "fragment": report["FragmentPath"],
            "dropins_present": bool(report["DropInPaths"]),
            "state": report["ActiveState"],
            "blockers": _blockers(unit, report),
        }
    return {
        "installed_units_inspected": True,
        "production_approved": False,
        "live_mutation_allowed": False,
        "units": result,
        "note": "Effective unit property snapshot only; script contents and installed changes remain unverified.",
    }
