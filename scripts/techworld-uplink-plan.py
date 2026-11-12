#!/usr/bin/env python3
"""Read-only Wi-Fi/Ethernet WAN selection preview. No network changes."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installer.uplink_selection import inspect, SelectionError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Preview current selected WAN uplink")
    parser.add_argument("--ap-radio", default=None,
                        help="Existing AP radio phy ID, e.g. phy0 (optional)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = inspect(ap_radio=args.ap_radio)
    except SelectionError as exc:
        print(json.dumps({"healthy": False, "error": str(exc)}, indent=2))
        return 1
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        selected = report["selected"]
        print(f"WAN: {selected['interface']} ({selected['kind']})")
        print(f"Default gateway: {selected['gateway']}")
        print(f"Route metric: {selected['metric']}")
        print(f"AP channel: {selected['ap_channel']} ({selected['channel_source']})")
        print("NOTE: Internet reachability and safe restart are NOT verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
