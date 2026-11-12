# Interactive wizard and existing-installation update

The project provides read-only network discovery and, **only on an existing running Techworld-WiFi installation**, an explicit-consent update for the SSID and local .test DNS record. This is **not** a complete fresh installer and it does not reconfigure the network uplink, bridge gateway, firewall or DHCP range.

```bash
bash install.sh --plan-only
bash install.sh --non-interactive
bash install.sh --json --ssid Techworld-WiFi --domain wireless.test
sudo bash install.sh
python3 -m unittest discover -s tests -v
```

The normal wizard prompts only for Wi-Fi SSID and captive portal domain. Its read-only discovery checks the active managed Wi-Fi default route, physical radio's station+AP concurrent mode, upstream channel, existing IPv4 interfaces and routes (including Docker, libvirt, and VPN). It preserves an existing Techworld bridge gateway for legacy adoption, or selects a non-overlapping private /24 network and derives DHCP automatically. Network choices are shown for review. Use `bash install.sh --advanced` to ask whether manual network overrides are desired; those changes are validated but are **not yet supported for live installation**. If discovery is ambiguous or radio concurrency is unsupported, planning stops safely.

It validates SSID byte length, DNS labels, `.local` avoidance, interface names, RFC1918 gateway, usable subnet and DHCP boundaries. Auto detection is a preflight, not proof that a concurrent AP will work on every Wi-Fi chipset. The eventual installer must test channel/interface combinations and re-check route/port conflicts immediately before modifying the system.

An already-running installation with no ownership manifest is **adoption_required**. The wizard offers to apply the supported SSID/DNS change only after explicit Y/yes consent, root permissions and a fresh verification of existing service files and gateway. It backs up modified files, restarts only affected child services, checks their health and attempts rollback on failure. N/Enter cancels without changes. `--plan-only`, `--json` and noninteractive execution without `--yes` stay read-only. Preflight `conflict` and `inspection_failed` block planning. A new clean machine will show a plan but cannot yet be installed.

**Production note:** `.test` is for local development. Production HTTPS and M-Pesa integration need a real domain and secure callback configuration. The current click-to-continue mechanism is not a paid access authorization mechanism.

Next implementation phases: package and configuration templates, full installation ownership manifest, comprehensive rollback, safe gateway and interface migration, update/repair support, and finally uninstall. Never uninstall unrelated `dnsmasq`, `NetworkManager`, Caddy, Docker, libvirt or hostapd services.
