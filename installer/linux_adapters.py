"""Allowlisted Linux command adapters for *offline* production integration tests.

NOT exposed as an executable or wired into systemd. Construction requires
an injected command executor; no default executor and no silent shell calls.
Use only after crash recovery, regulatory checks and owner-safe stop paths
have been implemented and verified on disposable hardware.
"""
import json


class AdapterError(RuntimeError):
    pass


UNITS = frozenset({
    "techworld-hotspot", "techworld-ap", "techworld-hostapd",
    "techworld-dhcp", "techworld-nat", "techworld-isolation", "opennds",
})


class ServiceAdapter:
    def __init__(self, execute):
        if not callable(execute):
            raise TypeError("Explicit service command executor required")
        self._execute = execute

    @staticmethod
    def _check(unit):
        if unit not in UNITS or type(unit) is not str:
            raise AdapterError("Refusing non-Techworld or unknown service")

    def state(self, unit):
        self._check(unit)
        value = self._execute(["systemctl", "show", "-p", "ActiveState",
                               "--value", unit]).strip()
        if value not in {"active", "inactive", "failed", "activating",
                         "deactivating", "reloading", "maintenance"}:
            raise AdapterError(f"Unverifiable unit state: {unit}")
        return value

    def start(self, unit):
        # Children must be controlled by the parent transaction, not directly.
        if unit != "techworld-hotspot":
            raise AdapterError("Only the Techworld parent may be started")
        return self._execute(["systemctl", "start", unit])

    def stop(self, unit):
        self._check(unit)
        return self._execute(["systemctl", "stop", unit])


class LinkInspectionAdapter:
    """Read-only Linux interface inventory; not a network mutator."""

    def __init__(self, execute):
        if not callable(execute):
            raise TypeError("Explicit command executor required")
        self._execute = execute

    def read(self, command):
        if not isinstance(command, list) or command not in (
            ["ip", "-j", "-d", "link", "show"],
            ["iw", "dev", "ap0", "info"],
        ):
            raise AdapterError("Unapproved interface inspection")
        return self._execute(command)

    def inspect(self, name):
        if name not in ("ap0", "br-techworld"):
            raise AdapterError("Unapproved interface name")
        raw = json.loads(self.read(["ip", "-j", "-d", "link", "show"]))
        if not isinstance(raw, list) or not all(isinstance(x, dict) for x in raw):
            raise AdapterError("Invalid link inventory")
        matches = [x for x in raw if x.get("ifname") == name]
        if len(matches) > 1:
            raise AdapterError("Ambiguous link inventory")
        if not matches:
            return None
        link = matches[0]
        index = link.get("ifindex")
        if type(index) is not int or index <= 0:
            raise AdapterError("Invalid link identity")
        if name == "br-techworld":
            kind = link.get("linkinfo", {}).get("info_kind")
            if kind != "bridge":
                return {"ifindex": index, "kind": "unverified"}
            return {"ifindex": index, "kind": "bridge"}
        info = self.read(["iw", "dev", "ap0", "info"])
        return {"ifindex": index,
                "kind": "AP" if any(line.strip() == "type AP"
                                    for line in info.splitlines()) else "unverified"}

    def create(self, *_args):
        raise AdapterError("Live interface creation is disabled")

    def remove(self, *_args):
        raise AdapterError("Live interface deletion is disabled")
