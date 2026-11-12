#!/usr/bin/env python3
"""Read-only report of repository AP/systemd integration blockers.

This script never runs systemctl, ip, iw or writes installed service files.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installer.deployment_audit import audit_repository


def main():
    root = Path(__file__).resolve().parents[1]
    report = audit_repository(root)
    report["integration_status"] = "blocked"
    report["live_execution_allowed"] = False
    report["required_before_activation"] = [
        "Replace legacy name-only AP/bridge cleanup with verified ownership",
        "Provide authorized network creation/removal adapter with crash recovery",
        "Validate uplink reachability and actual host regulatory restrictions",
        "Verify installed unit overrides and unit dependency stop ordering",
        "Test startup/shutdown on isolated hardware before workstation",
    ]
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
