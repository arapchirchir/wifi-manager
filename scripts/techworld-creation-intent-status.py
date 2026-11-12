#!/usr/bin/env python3
"""Inspect pending interface creation intents without changing networking."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installer.creation_intent import inspect_intents, IntentError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only interface intent audit")
    parser.add_argument("--receipt-dir", required=True,
                        help="Existing private owner-only transaction directory")
    args = parser.parse_args(argv)
    try:
        report = inspect_intents(args.receipt_dir)
    except (OSError, ValueError, IntentError) as exc:
        report = {
            "error": str(exc),
            "manual_review_required": True,
            "safe_to_restart": False,
            "automatic_cleanup_allowed": False,
        }
    print(json.dumps(report, sort_keys=True, indent=2))
    # This never serves as clearance to start a live hotspot.
    return 1


if __name__ == "__main__":
    sys.exit(main())
