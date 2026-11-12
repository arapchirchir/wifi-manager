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

## AP creation transaction (development, not deployed)

`installer/ap_transaction.py` now records each newly created AP or bridge
interface in a private, exclusive ownership receipt and rolls back created
interfaces in reverse order after a failed transaction. It checks both Linux
interface index and interface type at cleanup. If AP identity is uncertain,
the bridge is retained rather than deleted.

This module is exercised with fake network adapters only. It does **not**
yet replace the legacy shell preparation/cleanup scripts, and a crash
between interface creation and writing its receipt still requires a recovery
design. A production adapter, process-level transaction lock, dynamic
uplink configuration, and reliable hostapd rollback must be in place before
supervised live startup. Do not copy this branch's scripts to the host yet.

## Hostapd configuration rollback (development, not deployed)

`installer/hostapd_transaction.py` validates the dedicated hostapd file,
changes the legacy 2.4 GHz channel atomically, and can restore the previous
contents after an unsuccessful setup. A rollback refuses to overwrite
another process's later changes. The tests use disposable files only.

**Phase 1 is not complete:** the AP creation transaction, ownership-aware
cleanup, hostapd rollback and supervisor are still separate components.
The production adapter, locking, crash recovery, hardware channel changes
and systemd deployment have not been integrated. Avoid executing the live
hotspot on the single-radio workstation until this work is finished.

## Coordinated AP and hostapd transaction (development)

`installer/network_transaction.py` combines the verified upstream snapshot,
reversible channel update and ownership-recorded AP creation in one
transaction. If AP creation fails or the upstream snapshot changes, the
orchestrator attempts both interface and configuration rollback. The new
offline integration tests cover successful preparation, AP creation failures,
upstream changes and unsupported channels.

This has **not** been connected to the live startup service. Safe deployment
still requires a production network adapter, an exclusive lock, persisted
crash recovery and package/service configuration integration. The legacy
installed scripts are unchanged. Do not use `--execute` yet.

## Dynamic WAN selection preview (Issue #2)

The read-only `installer/uplink_selection.py` now compares connected Wi-Fi
and Ethernet IPv4 default routes, respects route metrics, prefers Ethernet
on equal metrics, verifies Wi-Fi association and refuses ambiguous routes.
No NetworkManager profile or firewall setting is modified.

```bash
python3 scripts/techworld-uplink-plan.py --json
```

A default gateway does **not** prove real internet access. For Ethernet,
the available AP radio and regulatory channel must still be validated. A
live Wi-Fi to Ethernet transition, restart, crash recovery and installation
integration are **not implemented**. Keep GitHub issue #2 open and don't
start the hotspot based on this read-only selection alone.

## Automatic WAN and AP radio planning (Issue #2, read-only)

Use `python3 scripts/techworld-network-plan.py --json` to inspect the
current WAN default route plus available Wi-Fi PHYs, and choose a compatible
legacy 2.4 GHz AP channel where the advertised radio capabilities permit.
For a single radio, the AP channel must follow the associated Wi-Fi uplink.
For Ethernet WAN, AP-capable idle Wi-Fi hardware must be available. Ambiguous
radio choices fail closed rather than guessing; `--ap-radio phyN` can
resolve a choice after inspection.

The `installer/restart_decision.py` comparison detects SSID, gateway,
WAN interface, AP radio, and channel changes. It reports when supervised
reconfiguration and consent are needed; **it does not perform a restart**.

The read-only plan now verifies the selected PHY is not soft- or hard-blocked
by rfkill, shows the detected regulatory country (without claiming full
regulatory compliance), and makes the selected WAN AP channel consistent with
the resolved AP radio. A blocked or missing PHY rfkill entry causes refusal.

Remaining work: complete regulatory-domain/channel validation, Internet
reachability, live transition/restart, locking, crash recovery and end-to-end
deployment.
The legacy installed scripts are unchanged. Do not enable the hotspot yet.

## Coordinated startup and recovery simulation

`installer/startup_controller.py` now combines upstream identity checks,
exclusive private locking, ownership-recorded AP setup, hostapd channel
updates, injected Techworld service startup and post-start verification.
Failure paths stop only enumerated Techworld services, verify their state,
remove only receipt-matched interfaces, and restore the original hostapd
configuration only when service shutdown and config identity are confirmed.

`installer/setup_lock.py` uses a private 0700-owned directory and a
nonblocking file lock; simultaneous simulated startups are refused. Tests
include partial service failures, upstream changes, unknown interface
ownership, repeated locking and failed stop cleanup. These tests use **mocked
service and network adapters** and temporary files, not the real laptop.

**Not production ready:** the live legacy systemd units and shell
preparation/cleanup scripts remain separate from this controller. In
particular, interface creation and the ownership receipt are not yet
crash-atomic, service and lock interoperability with legacy processes is
not guaranteed, and there is no durable post-crash recovery journal or
actual upstream Internet reachability verification. Do not execute live
startup, enable the installed hotspot, or merge this as production-ready.

## Production safety gate (draft PR #4)

The receipt-checked cleanup now refuses to delete `br-techworld` if **any**
interface is still attached to it, including interfaces outside Techworld's
ownership records. Link inventory errors also cause refusal rather than
deletion. This is exercised with simulated link inventories.

`installer/deployment_audit.py` provides a read-only static source audit of
the repository's legacy AP service and shell cleanup paths. Those paths
currently include name-only interface deletion and are **not** safe to deploy
on the workstation. The audit intentionally never declares production
readiness, even if no static patterns are detected.

The new checks are offline protection only. They do not replace installed
systemd units, supply a production network mutator, persist a crash recovery
journal or repair partially created interfaces after power loss. **Do not
activate the hotspot or deploy the legacy cleanup scripts based on this PR.**

## Durable recovery marker (development)

`installer/recovery_journal.py` writes a private, fsynced
`startup-journal.json` **before** the injected startup controller can change
network configuration or create interfaces. The record remains present after
both success and failure. A pending record after a crash, or a completed
record from an earlier run, blocks further startup until a separate,
ownership-aware manual review workflow is built. The marker cannot authorize
deletion or service changes. It deliberately does not contain passwords.

Inspect a known private directory without changing services:

```bash
python3 scripts/techworld-recovery-status.py --journal-dir /path/to/private/receipt-dir --json
```

This is a development-only feature. The current installed systemd units do
**not** use this journal, and no reviewed process for clearing it exists.
The marker cannot make interface creation/receipt persistence atomic and
does not enable automatic crash recovery. The existing legacy cleanup
scripts are still unsafe and must not be deployed. Do not start the
hotspot based on this marker or on offline test results.

## Phase 6 Linux integration adapters (draft PR #6)

`installer/linux_adapters.py` contains a command-injection-only service
adapter that restricts service control to named Techworld units and starts
only the Techworld parent service. Its Linux link adapter observes reserved
interfaces with iproute2 and iw and verifies their indices and types.
**Creation and removal are explicitly disabled.** Neither adapter is a live
daemon, installer or systemd integration.

Run the read-only source audit from the development repository:

```bash
python3 scripts/techworld-integration-audit.py
```

The audit reports existing name-only deletion in the legacy AP setup and
service paths and lists the safeguards required before deployment. A nonzero
exit code indicates blocked integration, not a live network failure.

**Keep the hotspot stopped.** Existing installed service overrides are not
changed by this PR. The remaining steps include a verified network mutator,
crash-safe receipts, and tested service stop ordering on an isolated host.
Do not install or enable these draft modules on your workstation.

## Phase 6 service lifecycle safety gate (draft)

The read-only `installer/systemd_lifecycle.py` reviews all seven checked-in
Techworld systemd units and reports legacy AP stop/prepare paths, boot
activation risks and a proposed shutdown ordering with AP last. It never
stops services or deletes interfaces. It explicitly refuses to create a
live stop plan even when handed an asserted installed-unit review flag.

```bash
python3 scripts/techworld-service-lifecycle-audit.py
```

The command intentionally exits nonzero and does not inspect installed
systemd drop-ins or runtime unit overrides. **Do not use systemctl start,
stop, enable or restart for the hotspot** until loaded units, ownership-safe
cleanup, crash recovery and isolated-host tests have been reviewed. The
existing unit files are unchanged.

## Phase 6 effective-unit and link-identity audit (draft PR #8)

The read-only `installer/effective_unit_audit.py` inspects the loaded
systemd properties of the seven Techworld units through an explicit command
executor. It reports drop-ins, legacy AP startup and cleanup commands, and
unexpected unit fragments. It does **not** approve startup or shutdown, and
a property snapshot does not verify script contents or establish that the
system cannot change afterward.

```bash
python3 scripts/techworld-effective-unit-audit.py
```

This read-only command intentionally exits with code 1 to avoid treating
the output as deployment authorization. The cleanup inspector now also rejects
duplicate interface names/indices and malformed link inventories instead of
silently accepting ambiguous observations.

**Live interface mutation is still disabled.** Do not deploy the legacy
service files, start the hotspot or assume a successful audit makes the
single-radio laptop safe. A durable creation/ownership handshake and
isolated hardware tests are still outstanding.

## Phase 6 interface-creation intent records (draft PR #9)

The simulated AP transaction now writes a private, fsynced per-interface
`.intent.json` file **before** calling the injected adapter's create
operation. This complements the existing post-creation ifindex ownership
receipt and persistent startup journal.

If a process dies between kernel interface creation and the ifindex receipt,
the intent survives and refuses further automatic preparation. **An intent
alone cannot prove an interface was created or identify a particular live
interface, so it never permits deletion or adoption.** Intents deliberately
remain after simulated cleanup until a separately reviewed operator
resolution workflow exists. They are not automatically removed.

Read-only inspection of a private development test directory:

```bash
python3 scripts/techworld-creation-intent-status.py --receipt-dir /path/to/private/dir
```

This deliberately exits nonzero, never clears evidence, and does not
authorize a restart. The installed legacy AP scripts and systemd services
remain unchanged; live network mutators are disabled. Do not activate the
hotspot or deploy these draft changes as a production installer.

## Phase 6 read-only recovery reconciliation (draft PR #10)

`installer/recovery_reconciliation.py` compares the startup journal,
per-interface creation intents, recorded interface indices and observed
live AP/bridge identity. It distinguishes missing receipts, orphaned links,
stale/reused indices and otherwise consistent snapshots. All outputs
explicitly prohibit automatic cleanup or restart; matching records are
**not independent proof of ownership**.

For operator investigation of an existing private transaction directory:

```bash
python3 scripts/techworld-reconcile-status.py --receipt-dir /path/to/private/dir
```

The command only uses read-only `ip link show` and `iw dev info` and
reads local transaction records. Its nonzero exit code is intentional.
It cannot grant service activation or remove stale records. Future
manual reconciliation must verify installed service state, kernel and
radio identity, bridge members, configuration, and crash history before
any privileged remediation. No live systemd scripts or interfaces are changed.

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
