"""Read-only legacy service audit. Never starts or stops any unit.

Production service integration is forbidden while installed Techworld AP
preparation or cleanup can still remove interfaces merely by name. This
audit deliberately requires human review even when its static checks pass.
"""
from pathlib import Path
import re


LEGACY_UNSAFE_PATTERNS = (
    (re.compile(r"\biw\s+dev\s+ap0\s+del\b"), "name-only AP deletion"),
    (re.compile(r"\bip\s+link\s+(?:delete|del)\s+\"?\$?\{?BRIDGE\b"), "name-only bridge deletion"),
    (re.compile(r"\bip\s+link\s+delete\s+br-techworld\b"), "name-only bridge deletion"),
    (re.compile(r"(?m)^\s*ExecStop\s*=\s*.*\biw\s+dev\b"), "systemd ExecStop name-only deletion"),
    (re.compile(r"(?m)^\s*ExecStopPost\s*=\s*.*techworld-ap-cleanup\b"), "unverified legacy ExecStopPost"),
)


def audit_sources(sources):
    """Return static findings without executing any supplied script content."""
    findings = []
    for path, content in sources.items():
        for expression, reason in LEGACY_UNSAFE_PATTERNS:
            if expression.search(content):
                findings.append({"path": path, "reason": reason})
    return {"deployment_safe": False, "findings": findings,
            "note": "Read-only static scan only. Live service integration, crash recovery and ownership proof remain unverified."}


def audit_repository(root):
    names = ("systemd/techworld-ap.service",
             "scripts/techworld-ap-prepare",
             "scripts/techworld-ap-cleanup")
    sources = {}
    for name in names:
        file = Path(root) / name
        sources[name] = file.read_text(encoding="utf-8")
    return audit_sources(sources)
