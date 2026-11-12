"""Pure Wi-Fi/Ethernet transition decisions for supervised restart planning.

No service start/stop; never changes NetworkManager or Wi-Fi connections.
"""
def fingerprint(report):
    route = report["selected"]
    return {
        "interface": route["interface"],
        "kind": route["kind"],
        "gateway": route["gateway"],
        "ssid": route.get("ssid"),
        "channel": route.get("channel"),
        "phy": route.get("phy"),
        "ap_radio": report.get("ap_radio", {}).get("phy"),
        "ap_channel": report.get("ap_radio", {}).get("channel"),
    }


def transition(previous, current):
    """Return only an advisory outcome; reconfiguration requires consent."""
    if previous is None:
        return {"decision": "initial_setup", "requires_approval": True,
                "restart_safe": False, "changes": {}}
    old = fingerprint(previous)
    new = fingerprint(current)
    changes = {key: {"before": old[key], "after": new[key]}
               for key in old if old[key] != new[key]}
    if not changes:
        decision = "unchanged"
    else:
        decision = "needs_supervised_reconfiguration"
    return {"decision": decision, "requires_approval": bool(changes),
            "restart_safe": False, "changes": changes}
