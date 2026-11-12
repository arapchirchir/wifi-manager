# Interactive installation preview

The project currently provides a **non-destructive configuration wizard**. This is not a complete hotspot installer yet. It does not create interfaces, write files, stop services, install dependencies, or change the live hotspot.

```bash
bash install.sh
bash install.sh --non-interactive --uplink wlp109s0
bash install.sh --json --ssid Techworld-WiFi --domain wireless.test --uplink wlp109s0
python3 -m unittest discover -s tests -v
```

The wizard asks for Wi-Fi SSID, captive portal domain, wireless uplink, gateway IPv4 address/prefix, DHCP range start, and DHCP range end. It defaults to `Techworld-WiFi`, `wireless.test`, a detected managed Wi-Fi adapter, `10.77.77.1/24`, `10.77.77.50`, and `10.77.77.200`.

It validates SSID byte length, DNS labels, `.local` avoidance, interface names, RFC1918 gateway, usable subnet and DHCP boundaries. Validation prevents generating an invalid plan but does not replace checks for upstream-channel limitations, actual port/interface conflicts, or host network collisions.

An already-running installation with no ownership manifest is **adoption_required**: the wizard can print a configuration preview, but no modification or automatic adoption occurs. Preflight `conflict` and `inspection_failed` block planning.

**Production note:** `.test` is for local development. Production HTTPS and M-Pesa integration need a real domain and secure callback configuration. The current click-to-continue mechanism is not a paid access authorization mechanism.

Next implementation phases: read-only hardware and subnet conflict probes, package and configuration templates, ownership manifest, backup/rollback, explicit confirmation, update/repair mode, and finally uninstall. Never uninstall unrelated `dnsmasq`, `NetworkManager`, Caddy, Docker, libvirt or hostapd services.
