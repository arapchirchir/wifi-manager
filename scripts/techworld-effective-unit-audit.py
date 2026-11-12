#!/usr/bin/env python3
"""Read-only effective unit audit. No service startup, stop or modifications."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installer.effective_unit_audit import inspect_effective_units


def read_only(command):
    if command[:4] != ["systemctl", "show", "--no-pager", "--all"]:
        raise RuntimeError("Only read-only systemctl show is permitted")
    result = subprocess.run(command, text=True, capture_output=True,
                            timeout=8, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "systemctl inspection failed")
    return result.stdout


def main():
    try:
        report = inspect_effective_units(read_only)
    except (RuntimeError, OSError, ValueError) as exc:
        report = {"installed_units_inspected": False, "production_approved": False,
                  "live_mutation_allowed": False, "error": str(exc)}
    print(json.dumps(report, indent=2, sort_keys=True))
    # Never interpret the assessment as approval to use the legacy services.
    return 1


if __name__ == "__main__":
    sys.exit(main())
