# Interactive installation preview

The project currently provides a **non-destructive configuration wizard**. This is not a complete hotspot installer yet. It does not create interfaces, write files, stop services, install dependencies, or change the live hotspot.

```bash
bash install.sh
bash install.sh --non-interactive
bash install.sh --json --ssid Techworld-WiFi --domain wireless.test
python3 -m unittest discover -s tests -v
```

The normal wizard prompts only for Wi-Fi SSID and captive portal domain. Its read-only discovery checks the active managed Wi-Fi default route, physical radio's station+AP concurrent mode, upstream channel, existing IPv4 interfaces and routes (including Docker, libvirt, and VPN). It preserves an existing Techworld bridge gateway for legacy adoption, or selects a non-overlapping private /24 network and derives DHCP automatically. Network choices are shown for review. Use `bash install.sh --advanced` for manual overrides, which must still pass validation. If discovery is ambiguous or radio concurrency is unsupported, planning stops safely.

It validates SSID byte length, DNS labels, `.local` avoidance, interface names, RFC1918 gateway, usable subnet and DHCP boundaries. Auto detection is a preflight, not proof that a concurrent AP will work on every Wi-Fi chipset. The eventual installer must test channel/interface combinations and re-check route/port conflicts immediately before modifying the system.

An already-running installation with no ownership manifest is **adoption_required**: the wizard can print a configuration preview, but no modification or automatic adoption occurs. Preflight `conflict` and `inspection_failed` block planning.

**Production note:** `.test` is for local development. Production HTTPS and M-Pesa integration need a real domain and secure callback configuration. The current click-to-continue mechanism is not a paid access authorization mechanism.

Next implementation phases: read-only hardware and subnet conflict probes, package and configuration templates, ownership manifest, backup/rollback, explicit confirmation, update/repair mode, and finally uninstall. Never uninstall unrelated `dnsmasq`, `NetworkManager`, Caddy, Docker, libvirt or hostapd services.
