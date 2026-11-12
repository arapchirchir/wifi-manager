"""Effective unit inspection with fake output only. Never invokes systemctl."""
import unittest

from installer.effective_unit_audit import (
    PROPERTIES, inspect_effective_units, _parse,
)
from installer.systemd_lifecycle import LifecycleError, STOP_ORDER


def report(unit, **overrides):
    data = {key: "" for key in PROPERTIES}
    data.update({
        "Id": unit + ".service",
        "LoadState": "loaded",
        "ActiveState": "inactive",
        "FragmentPath": "/etc/systemd/system/" + unit + ".service",
    })
    data.update(overrides)
    return "\n".join(key + "=" + data[key] for key in PROPERTIES)


class EffectiveUnitsTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def executor(self, args):
        self.calls.append(args)
        return report(args[-1][:-8])

    def test_queries_all_seven_loaded_units_without_mutation(self):
        result = inspect_effective_units(self.executor)
        self.assertEqual(set(result["units"]), set(STOP_ORDER))
        self.assertFalse(result["production_approved"])
        self.assertFalse(result["live_mutation_allowed"])
        self.assertEqual(len(self.calls), 7)
        for command in self.calls:
            self.assertEqual(command[:4], ["systemctl", "show", "--no-pager", "--all"])
            self.assertNotIn("stop", command)
            self.assertNotIn("start", command)

    def test_drop_in_is_reported_as_blocker(self):
        def run(args):
            return report(args[-1][:-8], DropInPaths="/etc/systemd/system/techworld-ap.service.d/override.conf")
        result = inspect_effective_units(run)
        self.assertTrue(result["units"]["techworld-ap"]["dropins_present"])
        self.assertTrue(any("drop-ins" in x for x in result["units"]["techworld-ap"]["blockers"]))

    def test_legacy_cleanup_in_effective_execstop_is_blocked(self):
        def run(args):
            unit = args[-1][:-8]
            if unit == "techworld-ap":
                return report(unit, ExecStop="{ path=/bin/sh ; argv[]=/bin/sh -c iw dev ap0 del ; }")
            return report(unit)
        issues = inspect_effective_units(run)["units"]["techworld-ap"]["blockers"]
        self.assertTrue(any("legacy AP" in x for x in issues))

    def test_unknown_fragment_path_blocks(self):
        def run(args):
            return report(args[-1][:-8], FragmentPath="/tmp/techworld.service")
        issues = inspect_effective_units(run)["units"]["techworld-ap"]["blockers"]
        self.assertTrue(any("fragment" in x for x in issues))

    def test_unexpected_loaded_unit_id_blocks(self):
        def run(args):
            return report("NetworkManager")
        issues = inspect_effective_units(run)["units"]["techworld-ap"]["blockers"]
        self.assertTrue(any("identity mismatch" in x for x in issues))

    def test_missing_property_fails_closed(self):
        with self.assertRaises(LifecycleError):
            inspect_effective_units(lambda _: "Id=techworld-ap.service")

    def test_repeated_property_fails_closed(self):
        with self.assertRaises(LifecycleError):
            _parse(report("techworld-ap") + "\nId=techworld-ap.service")

    def test_unexpected_property_fails_closed(self):
        with self.assertRaises(LifecycleError):
            _parse(report("techworld-ap") + "\nUnexpected=hello")

    def test_noncallable_executor_fails_closed(self):
        with self.assertRaises(TypeError):
            inspect_effective_units(None)

    def test_failed_command_is_not_silenced(self):
        with self.assertRaises(RuntimeError):
            inspect_effective_units(lambda _: (_ for _ in ()).throw(RuntimeError("systemd unavailable")))


if __name__ == "__main__":
    unittest.main()
