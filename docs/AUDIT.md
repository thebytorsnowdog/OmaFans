# OmaFans audit

Source review of `main` at `277fcf3`, which includes merged pull request #2. Code changes from this review are [pull request #3](https://github.com/thebytorsnowdog/OmaFans/pull/3), [pull request #5](https://github.com/thebytorsnowdog/OmaFans/pull/5), and [pull request #6](https://github.com/thebytorsnowdog/OmaFans/pull/6). This note is [pull request #4](https://github.com/thebytorsnowdog/OmaFans/pull/4). The trust model stays in [SECURITY.md](../SECURITY.md). The earlier verification record is [SECURITY_REVIEW.md](SECURITY_REVIEW.md).

## Changes already on main

Pull request #2 reads `coretemp` and `k10temp` for the 92°C override. The daemon waits until the next two-second tick. The previous idle poll was 250 ms. A control click that arrives during a refresh is kept. A control socket whose peer is not root is refused. The unit file gained `PrivateNetwork=yes` and `ProtectProc=invisible`. The verification record says 0.1.2 had no new sustained-load run and no new machine run. This review does not repeat that work.

## Fix opened from this review

[Pull request #3](https://github.com/thebytorsnowdog/OmaFans/pull/3) changes how CPU inputs are chosen.

`Hardware._ensure_cpu` returned without scanning when `cpu_inputs` was empty. A `coretemp` or `k10temp` node that appeared after process start stayed invisible until the ThinkPad hwmon directory disappeared. `cpu_temperature` also kept reading a path after that directory's `name` file changed. In a fixture, the node was renamed to `nvme` and given the sample 120000. The old code returned 120000 as the CPU temperature.

The new code reads `name` before it accepts a sample. A name other than `coretemp` or `k10temp` causes a fresh bind. With no trusted input bound, the daemon scans again once each control interval. That interval is two seconds. The lowest manual duty remains 30%. The override still writes normal level 7, pwm value 255, when a trusted reading is at least 92000 millidegrees. A latched fault still blocks writes. Curves still use ThinkPad `temp1_input`.

[Pull request #5](https://github.com/thebytorsnowdog/OmaFans/pull/5) unpacks `SO_PEERCRED` with struct format `3I`. Account id 2147483648 now matches the uid stored at install. Uid 0 is still root, and a different id is still refused. Fan writes are unchanged.

[Pull request #6](https://github.com/thebytorsnowdog/OmaFans/pull/6) lets `remove` stop and delete the daemon when `/etc/modprobe.d/omafans.conf` has been edited. The edited file is left in place, so its kernel option is unchanged. Install still refuses to overwrite that file.

## Findings left in place

While `Controller.fault` is set, `tick` calls `recover_sensor` and returns. That path reads the ThinkPad sensor and does not write the fan. A hot CPU sample during recovery does not request level 7. Recovery continues only after firmware Auto was verified and the watchdog was disarmed. A level 7 write in that window would arm the watchdog again. The recovery tests require no further writes, so the path is unchanged. A missing ThinkPad sample must not force a faster fan write.

`plausible_temperature` accepts integers from 0 through 125000 millidegrees. `cpu_temperature` drops anything outside that range, and the override does not see it. `test_implausible_cpu_reading_does_not_force_full_speed` expects a sample of 200000 to leave manual mode at the previous duty. ThinkPad `temp1_input` outside the same range is treated as a missing sensor and latches the fault path. This review has no live `coretemp` or `k10temp` sample above 125000, so the cutoff is unchanged.

In firmware Auto, `tick` calls `safe` on every pass. `safe` writes `pwm1_enable` and then the watchdog. That write is how the daemon disarms the watchdog after manual mode. Skipping it could leave the watchdog armed. The writes are unchanged.

`Service.qml` runs a repeating timer of 3000 ms. Each firing starts `/usr/bin/python3 -I` on `omafans.py` with the argument `heartbeat`, unless a helper is already running. Keeping one Python process open for later heartbeats would change how the widget starts the client. That timer is not a fan-write defect, and the widget cannot be run here.

`Panel.applyCurve` sets `curveDraftTouched` to false before the daemon answers. `valid_curve` still rejects a curve that breaks the five-point rules, and the service copies the error into the panel. The draft hint no longer says the curve is edited. The panel is unchanged. This environment cannot load `Panel.qml`, so there is no local test for that flag. A later design pass will define shared UI tokens.

`release` returns 0 when the ThinkPad hwmon node is unavailable, and it does not call `safe`. The unit runs that command from `ExecStopPost`. How often the node is missing at that moment is unknown here. Returning a failure could also make `scripts/setup.py remove` keep the installed files, because `remove` continues only when the service result is `success`. The command is unchanged.

The unit sets `CapabilityBoundingSet=CAP_CHOWN CAP_DAC_OVERRIDE` for the whole process. The daemon chowns the socket at startup and writes sysfs afterwards. Dropping either capability was not tried. A dropped capability that broke a sysfs write could latch a fault, and that was not tested here. `systemd-analyze verify system/omafans.service` exited 0 with no output on systemd 255 in this environment. That check does not execute the daemon.

`_bind_cpu` stores at most 16 `temp*_input` paths, in sorted path order. The fixtures in this repository use fewer files than that. No fixture shows those paths bound to the wrong device. Whether a supported ThinkPad has more than 16 inputs is unknown here.

`serve` raises when `control_ready` is false, and the unit sets `Restart=no`. A start that races the `thinkpad_acpi` module exits and stays stopped. The widget then remains in monitoring. A restart loop was not added. A crash loop could keep arming the watchdog. The release check requires `Restart=no`.

`.github/workflows/checks.yml` installs Bandit with `pip install bandit==1.9.4` and does not pin an artifact hash. The checkout action and the gitleaks archive are pinned by hash. The Bandit install line is unchanged.

## Checks this review could not run

No ThinkPad was available, so this review did not write a fan, arm the kernel watchdog, suspend, reboot, or run a thermal load. Figures in [hardware-validation.md](hardware-validation.md) are the repository's existing record.

`qmltestrunner` and `omarchy` are not installed here. The QML suite and `omarchy plugin validate` were not run. CodeQL and gitleaks were not run again.

On the sensor-fix branch, `python3 -m unittest discover -s tests -v` passed 59 tests, `python3 scripts/check_release.py` passed, and Bandit 1.9.4 reported no issues in `omafans.py`, `fanctl.py`, and `scripts/setup.py`. The account-id branch passed 60 tests. The modprobe branch passed 58 tests. Each of those branches also passed `python3 scripts/check_release.py`. This documentation branch ran the Python suite and the release check against `main` plus this file. The suite passed 57 tests, and the release check passed.

Merging pull requests #3 and #5 does not replace a daemon already installed at `/usr/local/lib/omafans/omafans.py`. The update steps in the README still apply. Pull request #6 changes `scripts/setup.py`, which `remove` runs from the plugin tree.
