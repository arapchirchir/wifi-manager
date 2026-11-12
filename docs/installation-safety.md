# Installer safety and existing-installation detection

`python3 scripts/techworld-preflight.py` is the **read-only** first stage of the future interactive installer. It detects service-name collisions, an existing legacy Techworld-WiFi setup, reserved interfaces, TCP port 2050 occupancy and the installation ownership manifest. It never stops services, removes files, reloads networking, or changes firewall rules.

```bash
python3 scripts/techworld-preflight.py
python3 scripts/techworld-preflight.py --json
python3 scripts/techworld-preflight.py --json --strict
python3 -m unittest discover -s tests -v
```

Strict exit codes:

| Code | Meaning | Required installer behavior |
| --- | --- | --- |
| 0 | Clean | Safe to proceed to further checks |
| 10 | Recorded installation exists | Offer update, repair, uninstall or cancel; require confirmation |
| 20 | Legacy or unrecorded Techworld files exist | Offer review/adopt or cancel; do not delete automatically |
| 30 | Conflicting or unknown ownership | Stop before modifying anything |
| 40 | Inspection error or invalid manifest | Fail closed; fix diagnostics |

The proposed manifest format, to be written **only by the eventual installer**, is:

```json
{
  "schema_version": 1,
  "owner": "techworld-wifi",
  "units": ["techworld-hotspot.service", "techworld-ap.service"]
}
```

A manifest alone is **not proof** that a file or service may be deleted. Before replacement, the installer will verify tracked paths, inspect existing file content/hashes, back up changed files, ask for approval and restore configuration on failed installation.

A running system `dnsmasq.service`, `hostapd.service`, or `NetworkManager.service` is **informational**, not grounds for stopping it. It may serve unrelated applications. The future installer must check per-interface and per-address conflicts, especially DNS and DHCP ports, before binding.

The current local setup predates any manifest. It should be recognized as `adoption_required`, not treated as a clean install. Running the preflight will not interrupt the Wi-Fi hotspot.

This step does **not** include automatic adoption, service removal, interactive installer prompts, package installation or the Laravel portal. Those belong to later guarded steps.
