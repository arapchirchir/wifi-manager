#!/usr/bin/env python3
"""Fully read-only WAN/AP radio plan; never starts, stops or reconfigures."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from installer.uplink_selection import inspect, run, SelectionError
from installer.radio_selection import (parse_radios, choose_radio, RadioError,
                                       radio_block_state, regulatory_report)


def plan(*, reader=run, ap_radio=None):
    wan = inspect(reader=reader)
    radios = parse_radios(reader(["iw", "dev"]))
    infos = {}
    for phy in radios:
        infos[phy] = reader(["iw", "phy", phy, "info"])
    ap = choose_radio(radios, wan["selected"], infos, preferred=ap_radio)
    block = radio_block_state(reader(["rfkill", "list"]), ap["phy"])
    regulatory = regulatory_report(reader(["iw", "reg", "get"]))
    selected = dict(wan["selected"])
    candidates = [dict(candidate) for candidate in wan["candidates"]]
    if selected["kind"] == "wifi" and selected.get("phy") == ap["phy"]:
        selected["ap_channel"] = ap["channel"]
        selected["channel_source"] = ap["reason"]
        for candidate in candidates:
            if candidate["interface"] == selected["interface"] and candidate["gateway"] == selected["gateway"]:
                candidate["ap_channel"] = ap["channel"]
                candidate["channel_source"] = ap["reason"]
    return {**wan, "selected": selected, "candidates": candidates,
            "ap_radio": ap, "rfkill": block, "regulatory": regulatory,
            "restart_safe": False,
            "warnings": [
                "No external internet reachability verification",
                "Rfkill checked; regulatory rules not fully validated",
                "Live hotspot restart and rollback are not implemented",
            ]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only WAN/AP radio plan")
    parser.add_argument("--ap-radio", default=None,
                        help="Explicit PHY to resolve ambiguous AP radios")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = plan(ap_radio=args.ap_radio)
    except (SelectionError, RadioError, OSError, ValueError) as exc:
        print(json.dumps({"usable": False, "error": str(exc)}, indent=2))
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        route = result["selected"]
        print(f"WAN: {route['interface']} ({route['kind']})")
        print(f"Gateway: {route['gateway']}")
        print(f"AP radio/channel: {result['ap_radio']['phy']}/{result['ap_radio']['channel']}")
        print("Read-only plan; live restart remains disabled.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
