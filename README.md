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

For a single-radio adapter, the hotspot's channel needs to follow the upstream association. The repository's `installer/channel_config.py` can render a matching hostapd configuration without writing to the system. The revised `scripts/techworld-ap-prepare` rejects an incorrect channel before modifying the network. **The full deployment integration is not complete:** do not copy these scripts over the live installation or restart the hotspot until the guarded update and recovery process is ready. A router that changes channels after startup still needs a supervised recovery mechanism.

## Security and limitations

- Existing Techworld units with no installer manifest are classified as adoption-required; the updater never deletes them automatically.
- Other running dnsmasq, hostapd, NetworkManager, Docker, Caddy and libvirt services are preserved.
- Conflicting or ambiguous network configuration causes validation to stop safely.
- Never commit live configuration secrets, API keys or M-Pesa credentials.
- Production deployments require a real domain with trusted HTTPS; .test is reserved for local development.
- A DNS record for wireless.test does not yet provide a Laravel portal or HTTPS endpoint.

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
