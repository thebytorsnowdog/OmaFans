# Live hardware validation

On **2026-10-07**, OmaFans replaced the previous fan controller and bar widget
on a **ThinkPad T480s**. The system service and new widget were left running in
Curve mode. This is a measured check on one laptop, not hardware certification
or a claim of compatibility with every ThinkPad.

## Tested source and environment

- Runtime commit: [`f3f2847379456018c48d487681f4e4abebc6345d`](https://github.com/thebytorsnowdog/omafans/commit/f3f2847379456018c48d487681f4e4abebc6345d).
- Controller SHA-256: `dffaa570b75efb01570402dc9f7a295278181a72a49500b2ef3c6aed44635dae`.
  The privileged harness verified that the installed root-owned controller
  matched the checkout. The installed widget's controller copy also matched.
- Omarchy **4.0.4-1**, kernel **7.2.5-3-omarchy**, systemd **261.2-1-arch**.
- `thinkpad_acpi` control was already enabled. OmaFans' explicit kernel option
  replaced the previous controller's option; the driver was not unloaded.
- The daemon used the repository's systemd sandbox and root-owned files.
  The widget was installed and updated using native `omarchy plugin` commands
  against this public Git repository.

The accompanying [JSON evidence](hardware-validation.json) contains selected
readings and results. Names, account IDs, home paths, serials, hostnames, boot
identifiers and full machine logs are excluded. These are local observations,
not independently attested measurements. Later documentation-only commits do
not change the runtime identity above.

## Observed results

| Check | Result |
| --- | --- |
| Manual 100% | Driver reported manual mode, PWM 255 (level 7), watchdog 45 seconds; fan settled around 5,076 RPM |
| Manual 70% | PWM 182 (level 5, reported 71%), confirming discrete-level rounding |
| Curve | At 64°C the saved curve selected PWM 109 (level 3, reported 43%) |
| Auto | Firmware mode `pwm1_enable=2`, watchdog disarmed |
| Invalid zero-duty request | Daemon rejected the request; the previous PWM value remained unchanged |
| Heartbeat expiry | With widget heartbeats absent, manual control returned to Auto after 16.04 seconds; a later heartbeat did not resume Manual |
| Kernel watchdog | While the daemon was stopped with SIGSTOP, a new kernel watchdog event appeared after 48.36 seconds; the fan remained at PWM 255, about 5,080 RPM |
| Resume after watchdog check | Daemon resumed into healthy Auto after its expired heartbeat |
| Graceful service stop | Starting from Manual, stop restored firmware Auto, cleared the watchdog and removed the control socket; systemd reported success |
| Service restart | Started healthy in Auto; enabled for future boots |
| Peer authorization | A socket connection from UID 0 was rejected because it was not the configured desktop UID; this tests the predicate, not protection against root |
| Widget control | Saved curve and 70% manual preference applied through live widget IPC; Curve stayed active across a 24.26-second observation, longer than the heartbeat expiry window |
| Final integration | OmaFans widget enabled; panel open/close commands succeeded and its status was healthy; former widget and system controller disabled |

The curve was `[[40,30],[55,40],[65,60],[75,80],[85,100]]` (°C, percent).
Readings are snapshots: fan inertia, changing load, the daemon's two-second
tick and the widget's three-second refresh mean RPM, temperature and duty are
not instantaneous synchronized measurements.

## Findings during installation and testing

The first system start exposed a permissions ordering bug: the daemon changed
socket ownership before applying mode 0600, which failed under its restricted
capabilities. Migration rolled back to the previous controller. The tested
commit fixes the ordering, setting the mode first; no capability was added.
The subsequent installation and stop/restart checks passed.

The first watchdog test incorrectly required firmware Auto at expiry. The fan
was already at level 7 and stayed there. The
[Linux driver implementation](https://github.com/torvalds/linux/blob/master/drivers/platform/x86/lenovo/thinkpad_acpi.c)
preserves that level in `fan_set_enable()`. The corrected retry required a new
kernel watchdog log event after a saved journal cursor, confirmed process state
`T` throughout the pause, and checked that PWM remained 255. The 45-second
watchdog event was observed at 48.36 seconds, including scheduling and polling
delay. The test held maximum normal cooling, enforced an 80°C abort threshold,
and always resumed the daemon and requested Auto in cleanup.

This proves firing and retention of the already-safe highest normal level on
this machine. It does not prove a lower-speed-to-Auto transition. See the
[kernel interface documentation](https://docs.kernel.org/admin-guide/laptops/thinkpad-acpi.html#fan-control-and-monitoring-fan-speed-fan-enable-disable)
for the driver-specific recovery semantics.

## Verification method and limits

Temporary local Python harnesses used the installed service, the normal
desktop-account CLI, direct sysfs read-back and a journal cursor. The privileged
harness performed SIGSTOP/SIGCONT and service stop/start with guaranteed cleanup.
The widget remained disabled during the heartbeat-expiry check, then was enabled
for the integration check. Harness exit statuses were zero for the successful
control and corrected system-safety runs. Original setup and failed-test logs
were retained privately for diagnosis and rollback.

Read-only checks for an installed system are:

```bash
systemctl is-active omafans.service
systemctl is-enabled omafans.service
python3 fanctl.py status
omarchy-shell community.omafans.service status
omarchy-shell community.omafans status
```

No reboot, suspend/resume, thermal stress, physical fan/sensor fault injection,
secondary-fan validation or other laptop model was tested. The 92°C override
was tested with fixtures, not by overheating the laptop. Enabled-at-boot is
configuration evidence only. A daemon restart intentionally returns to Auto;
manual and curve requests are not persisted across restarts.

The [security record](../SECURITY_REVIEW.md) covers source review, automated
tests, scanning and their separate limitations.
