#!/usr/bin/env python3
"""Read-only checked-in systemd unit lifecycle assessment."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installer.systemd_lifecycle import load_repository_units, LifecycleError


def main():
    try:
        report = load_repository_units(Path(__file__).resolve().parents[1])
    except (OSError, ValueError, LifecycleError) as exc:
        report = {"source_safe_to_deploy": False,
                  "installed_units_verified": False,
                  "error": str(exc)}
    print(json.dumps(report, indent=2, sort_keys=True))
    # Nonzero intentionally: never indicates a production-ready service plan.
    return 1


if __name__ == "__main__":
    sys.exit(main())
