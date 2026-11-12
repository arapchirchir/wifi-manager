#!/usr/bin/env python3
"""Read-only Techworld startup journal inspection. No recovery mutations."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installer.recovery_journal import read_journal, JournalError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect a private Techworld recovery journal")
    parser.add_argument("--journal-dir", required=True,
                        help="Existing, private owner-only journal directory")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        journal = read_journal(args.journal_dir)
    except (OSError, ValueError, JournalError) as exc:
        print(json.dumps({"status": "unverifiable", "safe_to_restart": False,
                          "error": str(exc)}, indent=2))
        return 1

    output = {"status": "absent" if journal is None else journal["state"],
              "safe_to_restart": False,
              "manual_review_required": journal is not None}
    if journal:
        output["channel"] = journal["channel"]
    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        print("Recovery marker:", output["status"])
        print("Live startup: NOT authorized by this inspection")
    return 0


if __name__ == "__main__":
    sys.exit(main())
