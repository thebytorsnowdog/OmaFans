# Live hardware validation

## Lifecycle and load checks — 0.1.1

On **2026-10-07**, the same T480s ran additional checks against runtime commit
`d93ef634fc1f87a9854ccfe2b9d8e5e5f1ad9c26`, installed controller SHA-256
`f721307de59a4562c3e97671585349b45dd8d1d96d4c3046a61c74afa0361b25`.
The runtime was unchanged. Selected raw observations are in
[lifecycle-validation.json](lifecycle-validation.json).

| Check | Observed result |
| --- | --- |
| Real deep sleep/resume | **Passed the documented recovery behavior.** A 45-second RTC wake alarm produced 43.52 seconds of measured sleep; kernel entry/exit records confirmed deep suspend, with no reboot or daemon restart |
| Sensor availability after wake | Initially unavailable, then valid but recovering; control became available after **8.27 seconds**, with six healthy samples total from 8.27 through 18.45 seconds |
| Safe behavior during recovery | Every post-wake sample showed firmware Auto (`pwm1_enable=2`) and watchdog disarmed; the old Curve request did not resume |
| Fresh request after recovery | A new Curve request was accepted, with manual hardware mode and watchdog 45 seconds; cleanup verified healthy firmware Auto and cleared the RTC alarm |
| Full CPU load | **Stopped at the test limit**, after about 3 seconds: eight busy workers, approximately 100% sampled CPU use, CPU peak 96°C, control sensor 70°C |
| Reduced CPU load | **Stopped at the test limit**, after about 13 seconds: eight workers at 40% duty, 51.4% average sampled system CPU use, CPU peak 95°C, control sensor peak 90°C |
| Reboot | **Not run.** A temporary read-only startup observer is prepared; a real reboot, startup observations and a post-boot installed-source hash check are still required |

Both load attempts planned 120 seconds, with independent CPU and controller
sensor readings and early-stop thresholds of **96°C CPU** and **90°C controller
sensor**. The CPU reported a critical threshold of 100°C. The test thresholds
were not changes to OmaFans. The full-load attempt reached the CPU threshold;
the reduced-duty attempt reached the controller-sensor threshold. All load
workers stopped, the daemon remained active, and cleanup returned control to
firmware Auto. Neither attempt completed its intended sustained interval.

During reduced load, hardware PWM rose from 109 to 255 and fan readings rose
from roughly 3,851 to 5,181 RPM. Temperature and control remained available with
no reported error in all load samples. These observations establish a response
to rising temperature, **not adequate cooling under sustained load**. The full
load's 96°C CPU versus 70°C control input also shows why the displayed input and
92°C override must not be treated as a hottest-CPU-core safeguard.

The initial suspend harness incorrectly required every post-wake sample to be
healthy immediately, so that assertion failed. The unchanged raw samples were
then checked against the documented sensor-recovery behavior: firmware Auto
throughout the gap, recovery within the 20-second observation window, continued
healthy readings and no automatic restoration of old Curve intent. Kernel
records, daemon continuity, installed-source identity and a fresh Curve command
were checked separately. This was **one actual suspend**, not a second trial
or physical sensor disconnection. Temporary unavailability after waking remains
visible until the sensor readings stabilize.

The evidence came from bounded Python CPU workers and one-second load samples,
`rtcwake -m no -s 45` followed by `systemctl suspend`, BOOTTIME versus monotonic
clock measurements, kernel journal entry/exit records, daemon/socket status,
and direct sysfs read-back. The load harnesses exited 1 after their temperature
stops. The original immediate-availability suspend assertion exited 1; the
documented-contract evaluation and remaining live control checks exited 0.
Private logs and full observations are retained locally; the public JSON omits
account details, absolute personal paths, process/boot identifiers and full logs.

**Outstanding:** reboot, sustained thermal stress, repeated sleep cycles,
physical fan/sensor fault injection, secondary fans and other laptop models.
The system was left in verified firmware Auto after these checks.

## Sensor recovery fix — 0.1.1

A later live report showed a valid temperature (63–69°C) while control remained
disabled with `Temperature sensor unavailable`. Version 0.1.0 had permanently
latched a previous failed read. Firmware Auto was active, but control never
became available again. The old daemon did not log the triggering read failure,
so its exact low-level cause is not established.

The installed fix is runtime commit
[`d93ef634fc1f87a9854ccfe2b9d8e5e5f1ad9c26`](https://github.com/thebytorsnowdog/omafans/commit/d93ef634fc1f87a9854ccfe2b9d8e5e5f1ad9c26),
controller SHA-256
`f721307de59a4562c3e97671585349b45dd8d1d96d4c3046a61c74afa0361b25`.
It clears only a sensor fault after verified firmware Auto, successful watchdog
disarming and three spaced valid readings. Old Manual/Curve intent is cleared;
write/watchdog faults and unsuccessful or manual fallback remain latched.

Validation on the same T480s included:

- **41 Python tests**, including reproducing the stuck-fault behavior before
  the fix, sample timing, interrupted recovery, startup sensor gaps, no old
  request resumption, and no watchdog writes after failed rescue.
- **Nine QML behavior tests**, including removal of the stale error and
  re-enabling controls when a recovered status arrives.
- A privileged harness using the **installed controller and real fan interface**,
  while the system daemon was stopped to avoid competing controllers. The
  harness simulated one unavailable temperature reading, confirmed immediate
  firmware Auto with watchdog disabled, then used actual sensor readings.
  Control recovered after **6.16 seconds** with **zero recovery writes**. A fresh
  Curve request was accepted. This was a simulated read failure, not physical
  sensor disconnection or a suspend/resume test.
- The installed system service then started under its normal sandbox. Manual
  100%, Manual 70%, Auto and Curve commands passed through the live widget,
  with hardware PWM and watchdog read-back. Panel status showed temperature and
  control available with no error.
- A further **two-minute** live observation kept Curve active with valid
  temperature readings, available control and no reported errors throughout.

Selected results are in [sensor-recovery-validation.json](sensor-recovery-validation.json).
The earlier measurements below apply to the initial runtime commit, and are
kept as historical evidence rather than being attributed to the new source.
The later lifecycle and load checks above supersede the untested sleep/load
status of this earlier run. Reboot remains untested; sustained thermal stress
has not passed.

## Initial installation — 0.1.0

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

At this initial 0.1.0 checkpoint, no reboot, suspend/resume, thermal stress, physical fan/sensor fault injection,
secondary-fan validation or other laptop model was tested. The 92°C override
was tested with fixtures, not by overheating the laptop. Enabled-at-boot is
configuration evidence only. A daemon restart intentionally returns to Auto;
manual and curve requests are not persisted across restarts.

The [security record](../SECURITY_REVIEW.md) covers source review, automated
tests, scanning and their separate limitations.
