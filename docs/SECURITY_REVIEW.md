# OmaFans security and verification record

Review date: 2026-10-07. Version: **0.1.1**.

This record summarises the threat model, protections and verification for
the experimental 0.1.1 release. It is not a claim of hardware certification.

## Threat model

The root daemon writes ThinkPad fan controls. Its attack surface is a local
Unix socket that only one authorised desktop account can use. Risks include
untrusted input from that account, a hung or crashed controller leaving the
fan in manual mode, and hardware or sensor faults. See [SECURITY.md](../SECURITY.md)
for the full trust model.

## Protections

- A bounded Unix-socket protocol authenticated using kernel peer credentials
  (mode 0600, exact UID check). There is no user-selected path, executable or
  shell-command interface.
- Strict settings validation, bounded JSON and request deadlines. Invalid
  types, oversized data, duplicate keys, deep nesting and non-finite values are
  rejected without changing fan settings.
- A daemon-owned heartbeat clock that includes suspend time. Stale or invalid
  heartbeats return control to Auto, and reconnecting does not resume an old
  manual setting.
- A kernel watchdog is armed before manual control. Watchdog arming and
  hardware write or read-back failures latch a visible fault.
- After its first recovery attempt, the daemon makes no further writes, so it
  cannot keep resetting the watchdog. There is no automatic systemd restart, and
  a regression test covers persistent write failures.
- The widget never elevates privileges. The installer, remover and hardened
  system unit are separate, explicit steps.
- Sensor-only recovery: after a temperature-sensor fault, control can clear
  only if firmware Auto was verified and the watchdog disarmed, followed by
  three spaced valid readings below 92°C. Recovery makes no hardware writes,
  stays in Auto and cannot resume an old Manual/Curve request. Other faults
  stay latched until an explicit service restart.

## Executed local evidence

| Check | Observed result |
| --- | --- |
| `python3 -m unittest discover -s tests -v` | 41 tests passed; fake hardware plus real Unix socket pairs; sensor recovery, failed-fallback latching and startup sensor gaps covered |
| QtTest service suite | Nine behavior tests plus init/cleanup passed; no failures; recovered status re-enables controls and clears the stale error |
| Bandit 1.9.4 | No outstanding findings on daemon, client and setup code; two narrow reviewed annotations described in SECURITY.md |
| Gitleaks 8.30.1 | No secrets found; CI scans the full Git history |
| Portable Omarchy validation | Valid manifest and entry points |
| Installed `omarchy plugin validate .` | Passed on Omarchy 4.0.4-1 |
| `systemd-analyze verify system/omafans.service` | Passed on systemd 261; syntax/dependency validation only |
| QML static analysis with installed host imports | No parse/import errors; dynamic host properties and a Quickshell enum produce unresolved static-type warnings |
| Live hosted widget | Monitoring status, panel open/close, disable/re-enable, rescan and fictional fixture loading passed |
| Preview | Real hosted QML with fictional readings; panel-only screenshot, manually inspected |
| Installation/update/removal fixtures | Fixed-file install/update/remove round trip passed; dry run, conflicts and failed-stop retention tested without root writes |
| Live system installation | Root-owned daemon runs under the supplied systemd unit on a T480s |
| Real hardware control and recovery | Manual, Curve, Auto, heartbeat expiry, paused-daemon kernel watchdog event and graceful stop/restart passed; [measurements and source identity](hardware-validation.md) |
| Sensor recovery fix | Simulated sensor loss using installed 0.1.1 controller with real hardware recovered in 6.16 seconds with no recovery writes; live widget modes and two-minute observation passed |
| Real deep sleep/resume | One 43.52-second sleep reproduced a temporary sensor gap; firmware Auto stayed active and control recovered after 8.27 seconds without restarting the daemon; a fresh Curve request passed |
| Real reboot | Changed boot verified; kernel fan-control setting retained, daemon active/enabled, old controller inactive, widget and sensors healthy in Auto; fresh Curve/Auto requests and protected installed-source hash verification passed |
| CPU load attempts | Full load stopped at the 96°C CPU test limit after about 3 seconds; reduced duty stopped at the 90°C control-sensor test limit after about 13 seconds. Fan ramping and healthy status were observed, but sustained thermal validation did not pass |
| Live Git installation/update | Native add and update from this public repository passed on the same T480s |

Exact source identity and CI results are attached to the Git commit and its
**Checks** workflow on GitHub. Rerun these checks after any change;
this document is not evidence for a later untested commit.

Raw evidence: [hardware-validation.json](hardware-validation.json),
[lifecycle-validation.json](lifecycle-validation.json) and
[sensor-recovery-validation.json](sensor-recovery-validation.json).

## Advisory findings reviewed

Omarchy's deterministic security linter reports QML process execution/output
collection, installation, privilege-tool references and service management.
These are intentional capabilities. The helper has bounded output and a
five-second QML deadline. Privileged work is confined to reviewed, separate
machine setup and the installed controller; the widget performs no elevation.
The additional CodeQL scan flagged group-write permissions on the local socket.
Access was narrowed to mode 0600 for the selected desktop account; the protected
parent directory and exact peer-UID checks remain in place.
Bandit's fixed-subprocess exceptions are explained in
[SECURITY.md](../SECURITY.md). No blanket rule exclusion was added.

These advisory checks are **not a security audit**, certification, warranty,
marketplace approval or a guarantee of adequate cooling.

## Limits and checks not performed

- Live control was checked on one T480s. One real deep sleep/resume cycle passed
  the documented safe-recovery behavior. CPU-load attempts stopped at test
  temperature limits; sustained thermal stress has not passed. One real reboot
  and post-login control cycle passed. Physical hardware fault injection remains
  untested. See the
  [lifecycle and load evidence](hardware-validation.md#lifecycle-and-load-checks--011).
  The 92°C safeguard has fixture evidence only. Watchdog firing was tested at level 7; a live
  transition from a lower level to firmware Auto was not tested.
- Only the first ThinkPad thermal input controls the 92°C override. Sensor
  mapping, other components, RPM accuracy, cooling effectiveness and secondary
  fans are not validated. During the full-load attempt, the hottest CPU reading
  reached 96°C while the control input read 70°C. The override is not a
  CPU-core temperature limit or proof of adequate sustained cooling.
- The UI was exercised on one horizontal-bar display, including a new desktop
  session after reboot. Vertical placement, multiple monitors and restarting
  the shell without reboot remain unverified.
- No other machine has been tested. Native add and update from Git passed on
  the T480s. Removal was tested with fixtures only, not on the live system.
- The root daemon uses only the standard library. Python, kernel, systemd, Qt
  and Quickshell patch levels are the operating system's responsibility; a
  Python dependency scanner cannot certify those components.
- No external penetration test or professional security audit was commissioned.

The [kernel fan interface documentation](https://docs.kernel.org/admin-guide/laptops/thinkpad-acpi.html#fan-control-and-monitoring-fan-speed-fan-enable-disable)
defines the watchdog and discrete fan levels. Driver behavior and support
remain model-dependent. Review the compatibility and residual-risk notes
before enabling control.
