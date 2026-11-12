#!/usr/bin/env python3
"""Read-only Techworld recovery reconciliation; never cleans interfaces."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installer.recovery_reconciliation import reconcile


def read(command):
    if command != ["ip", "-j", "-d", "link", "show"] and command != ["iw", "dev", "ap0", "info"]:
        raise RuntimeError("Unsupported inspection command")
    process = subprocess.run(command, capture_output=True, text=True,
                             timeout=8, check=False)
    if process.returncode:
        raise RuntimeError("Interface inspection failed: " + process.stderr.strip())
    return process.stdout


def main():
    parser = argparse.ArgumentParser(description="Read-only hotspot recovery assessment")
    parser.add_argument("--receipt-dir", required=True,
                        help="Existing private owned recovery directory")
    args = parser.parse_args()
    try:
        result = reconcile(args.receipt_dir, reader=read)
    except (OSError, ValueError, RuntimeError, TypeError) as exc:
        result = {"assessment_complete": False, "error": str(exc),
                  "safe_to_restart": False, "automatic_cleanup_allowed": False,
                  "manual_review_required": True}
    print(json.dumps(result, indent=2, sort_keys=True))
    # This command never grants activation approval.
    return 1


if __name__ == "__main__":
    sys.exit(main())
