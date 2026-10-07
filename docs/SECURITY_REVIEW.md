# OmaFans security and verification record

Review date: 2026-10-07. Version: **0.1.0**.

This record summarises the threat model, protections and verification for
the experimental 0.1.0 release. It is not a claim of hardware certification.

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

## Executed local evidence

| Check | Observed result |
| --- | --- |
| `python3 -m unittest discover -s tests -v` | 35 tests passed; fake hardware plus real Unix socket pairs |
| QtTest service suite | Eight behavior tests plus init/cleanup passed; no failures |
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

Exact source identity and CI results are attached to the Git commit and its
**Checks** workflow on GitHub. Rerun these checks after any change;
this document is not evidence for a later untested commit.

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

- Live control was checked on one T480s. No thermal stress test, hardware fault
  injection, suspend/resume or reboot test was performed. The 92°C safeguard
  has fixture evidence only. Watchdog firing was tested at level 7; a live
  transition from a lower level to firmware Auto was not tested.
- Only the first ThinkPad thermal input controls the 92°C override. Sensor
  mapping, other components, RPM accuracy, cooling effectiveness and secondary
  fans are not validated.
- The UI was exercised on one horizontal-bar display. Vertical placement,
  multiple monitors and full-shell restart behavior remain unverified.
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
