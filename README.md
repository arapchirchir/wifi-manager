# Techworld-WiFi Manager

Ubuntu wireless hotspot and captive portal management tools.

> **Development status:** A complete fresh installer and uninstaller do not exist yet. This development branch provides read-only hardware/network detection plus a limited, consented update for an **already configured and running** Techworld-WiFi hotspot. The Laravel/M-Pesa payment portal is not yet included.

## Current features

- Detects upstream Wi-Fi adapter, PHY, channel and advertised concurrent station+AP support.
- Includes a pure hostapd configuration renderer that derives the AP channel from the detected upstream channel, plus a pre-start guard that rejects mismatched STA/AP channels **before changing interfaces**. These are preparatory pieces, not yet deployed automatically on the host.
- Checks existing Techworld services, ports, interfaces, and shared system services.
- Preserves existing Techworld gateway or suggests an unused private subnet for planning.
- Prompts for Wi-Fi SSID and captive portal domain. Auto-detects uplink, gateway and DHCP range.
- After explicit approval, can update **only** the SSID and local .test DNS alias on an existing installation.
- Backs up changed configuration files under /var/backups/techworld-wifi/ and attempts rollback on failure.
- Includes offline unit tests and GitHub Actions CI.

## Get the development branch

This feature is in [draft pull request #1](https://github.com/arapchirchir/wifi-manager/pull/1), not yet merged into master.

```bash
git clone --branch feature/installer-preflight-safety https://github.com/arapchirchir/wifi-manager.git
cd wifi-manager
```

For an existing clone on the development branch, run `git pull --ff-only`.

## Preview without changes

```bash
./install.sh --plan-only
./install.sh --json
python3 scripts/techworld-preflight.py --json
```

These commands are read-only and do not require sudo.

## Update an existing running hotspot

Only run this on a computer with a verified, already-configured Techworld-WiFi setup. Review the source before executing any code with administrator privileges.

```bash
sudo ./install.sh
```

The wizard normally asks only for the SSID and local captive domain, for example:

```text
Wi-Fi SSID [Techworld-WiFi]: Wireless
Captive portal domain [wireless.test]:

SSID: Wireless
Portal: wireless.test
Gateway: 10.77.77.1/24 (detected)

Supported update: Wi-Fi SSID and local .test DNS alias only.
Apply these settings to the existing hotspot? [y/N]:
```

- Choose N or press Enter to abort with no changes.
- Choose Y to perform one more safety check, back up original config files, update the SSID and/or local DNS alias, validate dnsmasq configuration, restart affected Techworld child services, and verify they're active.
- Changing the SSID temporarily disconnects hotspot clients. They may need to reconnect using the new SSID.
- If something fails, the updater attempts to restore the previous files and restart the affected services. Review errors before continuing.
- If run without sudo, approval cannot change the system and the updater reports that root permissions are required.

### Advanced networking

```bash
sudo ./install.sh --advanced
```

Advanced mode first asks whether to customize detected network settings. Manual uplink, gateway or DHCP changes are not yet supported by the live updater. Such changes are rejected rather than risking a partial network migration.

## Channel synchronization safety

For a single-radio adapter, the hotspot's channel needs to follow the upstream association. The repository's `installer/channel_config.py` can render a matching hostapd configuration without writing to the system. The revised `scripts/techworld-ap-prepare` now reads the active upstream channel and, for the existing 2.4 GHz `hw_mode=g` configuration on channels 1-11, backs up and atomically synchronizes the dedicated hostapd channel **before** modifying the AP or bridge interfaces. If the upstream isn't associated or the band/configuration is unsupported, preparation stops. **Deployment and upstream recovery integration are not complete:** do not copy these scripts over the live installation or restart the hotspot until the supervised update and recovery process is ready. A router that changes channels after startup still needs a supervised recovery mechanism.

## Security and limitations

- Existing Techworld units with no installer manifest are classified as adoption-required; the updater never deletes them automatically.
- Other running dnsmasq, hostapd, NetworkManager, Docker, Caddy and libvirt services are preserved.
- Conflicting or ambiguous network configuration causes validation to stop safely.
- Never commit live configuration secrets, API keys or M-Pesa credentials.
- Production deployments require a real domain with trusted HTTPS; .test is reserved for local development.
- A DNS record for wireless.test does not yet provide a Laravel portal or HTTPS endpoint.

## Read-only post-start checks

The new `scripts/techworld-post-start-health.py` verifies the upstream
NetworkManager association, default route, AP mode/channel alignment and five
Techworld service states. It **only inspects** the system. It does not
test actual Internet reachability, stop/restart services, change interfaces
or repair a dropped upstream connection.

Run it after a supervised hotspot startup:

```bash
python3 scripts/techworld-post-start-health.py --uplink wlp109s0 --json
```

Until the protected deployment and rollback flow is finished, do not start
the existing hotspot merely to run this checker. The script is not connected
to systemd yet, and a healthy result would not prove external Internet access.

## Experimental supervised startup (not deployed)

`scripts/techworld-supervised-start.py` now provides a **read-only default**
startup plan and a separate explicit-consent path. It verifies the upstream
connection before requesting a hotspot start, checks the hotspot afterward,
and attempts to stop `techworld-hotspot` if the startup fails. It never
issues changes to NetworkManager profiles or restarts shared DNS services.

```bash
python3 scripts/techworld-supervised-start.py --uplink wlp109s0 --json
```

**Do not use `--execute` on the host yet.** This is development code that
has only been tested with mocked systemd and Wi-Fi calls. The full rollback
must also account for child services left active after partially failed
systemd transactions, preserve the upstream association across AP teardown,
and handle connectivity recovery without losing the host's internet access.
It is not yet integrated with the installer or systemd units. Do not equate
service `active` status with proven internet reachability.

## Interface ownership receipts (development only)

The new `installer/ownership_receipt.py` can create an exclusive, mode-0600
interface creation record within a pre-existing private directory, and
validates it when read. `installer/resource_ownership.py` compares the
recorded names, types and interface indices with observed live state before
planning any removal. An interface name alone does not establish ownership.

**Not connected to AP preparation or cleanup yet.** The running host has no
new ownership receipts and the installed cleanup script remains unchanged.
Do not deploy the scripts or start the hotspot until creation receipts,
partial-failure cleanup, and rollback behavior are integrated and tested.

## Offline tests

```bash
python3 -m unittest discover -s tests -v
```

Tests use mock service commands and temporary files, not the host networking stack.

## Managing an already installed hotspot

```bash
sudo systemctl status techworld-hotspot
sudo systemctl stop techworld-hotspot
sudo systemctl start techworld-hotspot
```

## Not implemented yet

- Complete fresh Ubuntu installation, including dependencies and portable configuration generation.
- Full existing-installation adoption manifest and an uninstall.sh.
- Safe on-device migration of uplink, channel, gateway, subnet or DHCP range.
- Laravel portal, public TLS, package pricing, and M-Pesa payment-gated authentication.

Additional details: [installation safety](docs/installation-safety.md) and [interactive wizard](docs/interactive-wizard.md).
