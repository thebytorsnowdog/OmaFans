# OmaFans security and verification record

Review date: 2026-10-07. Candidate version: **0.1.0**.

The source in this repository was reviewed before public publication. The
original local widget was separated from its machine-specific integration,
renamed, and given a new privileged boundary. The scope is an experimental
source release for review and testing, not a claim of hardware certification.

## Changes resulting from the review

- Replaced root reads of user-writable state and heartbeat files with a bounded
  Unix-socket protocol authenticated using kernel peer credentials. The daemon
  has no user-selected path, executable or shell-command interface.
- Removed names and home paths from the source and system unit. Repository
  commits use a project identity. The public GitHub repository owner remains
  visible; privacy checks do not imply anonymous hosting.
- Added strict settings validation, bounded JSON and request deadlines. Invalid
  types, oversized data, duplicate keys, deep nesting and non-finite values are
  rejected without changing fan settings.
- Replaced file timestamps with a daemon-owned heartbeat clock that includes
  suspend time. Stale or invalid heartbeat ages return requests to Auto;
  reconnecting does not silently resume an old manual setting.
- Made watchdog arming and hardware write/read-back failures visible. Manual
  control depends on a watchdog, and faults latch control off.
- An independent source review caught watchdog starvation during repeated
  recovery attempts. The fix stops further writes after the initial fault
  recovery and disables automatic systemd restart. A regression reproduces
  persistent write failures and verifies that 100 subsequent ticks and
  heartbeats cannot reset the watchdog again.
- Removed the broken secondary QML parsing path, serialized helper calls, and
  added a helper timeout. The widget never runs privileged setup itself.
- Added an explicit installer/remover, protected system files, a hardened
  system unit, license, documentation, fixture tests and CI security checks.

## Executed local evidence

| Check | Observed result |
| --- | --- |
| `python3 -m unittest discover -s tests -v` | 35 tests passed; fake hardware plus real Unix socket pairs |
| QtTest service suite | Eight behavior tests plus init/cleanup passed; no failures |
| Bandit 1.9.4 | No outstanding findings on daemon, client and setup code; three narrow reviewed annotations described in SECURITY.md |
| Gitleaks 8.30.1 | No secrets found in candidate source; full-history scan also required before publication |
| Targeted personal-information scan | No personal names, personal mail addresses or home paths in candidate files |
| Portable Omarchy validation | Valid manifest and entry points |
| Installed `omarchy plugin validate .` | Passed on Omarchy 4.0.4-1 |
| `systemd-analyze verify system/omafans.service` | Passed on systemd 261; syntax/dependency validation only |
| QML static analysis with installed host imports | No parse/import errors; dynamic host properties and a Quickshell enum produce unresolved static-type warnings |
| Live hosted widget | Monitoring status, panel open/close, disable/re-enable, rescan and fictional fixture loading passed |
| Desktop restoration | Original shell configuration bytes, workspace and cursor restored; temporary plugin removed |
| Preview | Real hosted QML with fictional readings; panel-only screenshot, manually inspected |
| Installation/update/removal fixtures | Fixed-file install/update/remove round trip passed; dry run, conflicts and failed-stop retention tested without root writes |

Exact source identity and CI results are attached to the Git commit and its
**Checks** workflow on GitHub. Rerun these checks when changing the candidate;
this document is not evidence for a later untested commit.

## Advisory findings reviewed

Omarchy's deterministic security linter reports QML process execution/output
collection, installation, privilege-tool references and service management.
These are intentional capabilities. The helper has bounded output and a
five-second QML deadline. Privileged work is confined to reviewed, separate
machine setup and the installed controller; the widget performs no elevation.
Bandit's socket-mode and fixed-subprocess exceptions are explained in
[SECURITY.md](SECURITY.md). No blanket rule exclusion was added.

These advisory checks are **not a security audit**, certification, warranty,
marketplace approval or a guarantee of adequate cooling.

## Limits and checks not performed

- No real fan writes, daemon installation under the live systemd sandbox,
  physical watchdog-expiry test, thermal stress test, hardware fault injection
  or suspend/resume test of the privileged daemon was performed. The installed
  controller on the development machine was preserved.
- Only the first ThinkPad thermal input controls the 92°C override. Sensor
  mapping, other components, RPM accuracy, cooling effectiveness and secondary
  fans are not validated.
- The UI was exercised on one horizontal-bar display. Vertical placement,
  multiple monitors and full-shell restart behavior remain unverified.
- Native Git-based plugin add/update/removal is documented but has not been
  exercised against this public repository on a separate machine. Lifecycle
  tests used a temporary copy of the candidate runtime files.
- The root daemon uses only the standard library. Python, kernel, systemd, Qt
  and Quickshell patch levels are the operating system's responsibility; a
  Python dependency scanner cannot certify those components.
- No external penetration test or professional security audit was commissioned.

The [kernel fan interface documentation](https://docs.kernel.org/admin-guide/laptops/thinkpad-acpi.html#fan-control-and-monitoring-fan-speed-fan-enable-disable)
defines the watchdog and discrete fan levels. Driver behavior and support
remain model-dependent. Review the compatibility and residual-risk notes
before enabling control.
