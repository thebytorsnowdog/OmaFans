import copy
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import omafans as app


class Hardware:
    available = True

    def __init__(self):
        self.values = {"pwm1_enable": 2, "pwm1": 255, "fan1_input": 2400}
        self.temp = 45000
        self.cpu = None
        self.ready = True
        self.events = []
        self.failed = set()

    def control_ready(self):
        return self.ready

    def temperature(self):
        return self.temp

    def cpu_temperature(self):
        return self.cpu

    def read(self, name):
        return self.values.get(name)

    def write(self, name, value):
        self.events.append((name, value))
        if (name, value) in self.failed:
            return False
        self.values[name] = value
        return True

    def watchdog(self, value):
        self.events.append(("watchdog", value))
        return ("watchdog", value) not in self.failed


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.hardware = Hardware()
        self.now = 100.0
        self.control = app.Controller(self.hardware, lambda: self.now)

    def set_manual(self, value=30):
        return self.control.request({"command": "set", "settings": {"mode": "manual", "manual_percent": value}})

    def test_manual_arms_watchdog_before_writes_and_reports_observation(self):
        result = self.set_manual()
        self.assertTrue(result["ok"])
        self.assertEqual(self.hardware.events[:3], [("watchdog", 45), ("pwm1_enable", 1), ("pwm1", 109)])
        self.assertEqual(result["percent"], 43)
        self.assertEqual(result["manual_percent"], 30)

    def test_every_manual_tick_rearms_watchdog(self):
        self.set_manual()
        self.control.tick()
        self.assertEqual(self.hardware.events.count(("watchdog", 45)), 2)

    def test_timeout_restores_firmware_without_resuming_old_request(self):
        self.set_manual()
        self.now += 16
        self.control.tick()
        self.assertEqual(self.hardware.values["pwm1_enable"], 2)
        self.control.request({"command": "heartbeat"})
        self.control.tick()
        self.assertEqual(self.control.state["mode"], "auto")

    def test_late_heartbeat_before_next_tick_also_clears_manual(self):
        self.set_manual()
        self.now += 16
        self.control.request({"command": "heartbeat"})
        self.control.tick()
        self.assertEqual(self.hardware.values["pwm1_enable"], 2)

    def test_clock_rollback_is_not_fresh(self):
        self.set_manual()
        self.now -= 30
        self.control.tick()
        self.assertEqual(self.control.state["mode"], "auto")

    def test_sensor_failure_returns_to_auto_then_recovers_without_resuming_manual(self):
        self.set_manual()
        self.hardware.temp = None
        self.assertFalse(self.control.tick())
        self.assertEqual(self.hardware.values["pwm1_enable"], 2)
        events = list(self.hardware.events)
        self.hardware.temp = 45000
        self.assertFalse(self.set_manual()["ok"])
        self.assertFalse(self.control.status()["control_enabled"])
        for index in range(3):
            self.now += 2
            self.assertEqual(self.control.tick(), index == 2)
        self.assertEqual(self.hardware.events, events)
        self.assertTrue(self.control.status()["control_enabled"])
        self.assertEqual(self.control.status()["error"], "")
        self.assertEqual(self.control.state["mode"], "auto")
        self.assertIsNone(self.control.last_heartbeat)
        self.control.request({"command": "heartbeat"})
        self.assertEqual(self.control.state["mode"], "auto")
        self.assertTrue(self.set_manual()["ok"])

    def test_sensor_recovery_requires_spaced_consecutive_valid_samples(self):
        self.hardware.temp = None
        self.control.tick()
        for temp in (45000, 45000, None, 45000, 45000, 92000):
            self.now += 2
            self.hardware.temp = temp
            self.assertFalse(self.control.tick())
        self.hardware.temp = 45000
        for _ in range(20):
            self.assertFalse(self.control.tick())
        self.now += 10  # A suspend-sized sampling gap restarts the streak.
        self.assertFalse(self.control.tick())
        self.now += 2
        self.assertFalse(self.control.tick())
        self.now += 2
        self.assertTrue(self.control.tick())

    def test_sensor_recovery_checks_firmware_mode_and_kernel_control(self):
        self.hardware.temp = None
        self.control.tick()
        self.hardware.temp = 45000
        events = list(self.hardware.events)
        for ready, enable in ((False, 2), (True, 1), (True, None)):
            self.hardware.ready = ready
            self.hardware.values["pwm1_enable"] = enable
            for _ in range(4):
                self.now += 2
                self.assertFalse(self.control.tick())
                self.assertNotIn("firmware Auto active", self.control.error)
        self.assertEqual(self.hardware.events, events)
        self.hardware.values["pwm1_enable"] = 2
        for _ in range(3):
            self.now += 2
            self.control.tick()
        self.assertTrue(self.control.status()["control_enabled"])

    def test_sensor_failure_with_only_manual_fallback_never_auto_recovers(self):
        self.hardware.failed.add(("pwm1_enable", 2))
        self.hardware.temp = None
        self.control.tick()
        self.hardware.failed.clear()
        self.hardware.temp = 45000
        events = list(self.hardware.events)
        for _ in range(100):
            self.now += 2
            self.assertFalse(self.control.tick())
        self.assertEqual(self.hardware.events, events)
        self.assertFalse(self.control.status()["control_enabled"])

    def test_write_fault_does_not_auto_recover_even_when_hardware_recovers(self):
        self.hardware.failed.add(("pwm1", 109))
        self.assertFalse(self.set_manual()["ok"])
        self.hardware.failed.clear()
        events = list(self.hardware.events)
        for _ in range(100):
            self.now += 2
            self.assertFalse(self.control.tick())
        self.assertEqual(self.hardware.events, events)
        self.assertFalse(self.control.status()["control_enabled"])

    def test_sensor_failure_with_failed_watchdog_disarm_stays_latched(self):
        self.hardware.failed.add(("watchdog", 0))
        self.hardware.temp = None
        self.control.tick()
        self.hardware.failed.clear()
        self.hardware.temp = 45000
        events = list(self.hardware.events)
        for _ in range(100):
            self.now += 2
            self.assertFalse(self.control.tick())
        self.assertEqual(self.hardware.events, events)
        self.assertFalse(self.control.status()["control_enabled"])

    def test_hot_cpu_overrides_a_cooler_thinkpad_sensor(self):
        self.set_manual(30)
        self.hardware.temp = 70000
        self.hardware.cpu = 96000
        self.control.tick()
        self.assertEqual(self.hardware.values["pwm1"], 255)
        self.assertEqual(self.hardware.values["pwm1_enable"], 1)
        self.assertEqual(self.control.state["mode"], "auto")
        self.assertIn("CPU", self.control.error)
        self.assertEqual(self.control.status()["cpu_temperature"], 96)

    def test_implausible_cpu_reading_does_not_force_full_speed(self):
        self.set_manual(30)
        self.hardware.temp = 70000
        self.hardware.cpu = 200000
        self.control.tick()
        self.assertEqual(self.hardware.values["pwm1"], 109)
        self.assertEqual(self.control.state["mode"], "manual")
        self.assertIsNone(self.control.status()["cpu_temperature"])

    def test_overheat_overrides_expired_client_and_clears_request(self):
        self.set_manual()
        self.now += 60
        self.hardware.temp = 92000
        self.control.tick()
        self.assertEqual(self.hardware.values["pwm1"], 255)
        self.assertEqual(self.hardware.values["pwm1_enable"], 1)
        self.assertEqual(self.control.state["mode"], "auto")
        self.hardware.temp = 60000
        self.control.tick()
        self.assertEqual(self.hardware.values["pwm1_enable"], 2)

    def test_watchdog_failure_blocks_manual(self):
        self.hardware.failed.add(("watchdog", 45))
        self.assertFalse(self.set_manual()["ok"])
        self.assertNotIn(("pwm1_enable", 1), self.hardware.events)
        self.assertIn("watchdog", self.control.error)

    def test_pwm_failure_reverts_to_firmware(self):
        self.hardware.failed.add(("pwm1", 109))
        self.assertFalse(self.set_manual()["ok"])
        self.assertEqual(self.hardware.values["pwm1_enable"], 2)

    def test_failed_readback_is_not_reported_as_success(self):
        with patch.object(self.hardware, "read", return_value=0):
            self.assertFalse(self.set_manual()["ok"])
        self.assertIn("verification failed", self.control.error)

    def test_auto_unsupported_uses_highest_normal_speed_and_keeps_watchdog(self):
        self.hardware.failed.add(("pwm1_enable", 2))
        self.assertTrue(self.control.safe())
        self.assertEqual(self.hardware.values["pwm1"], 255)
        self.assertNotIn(("watchdog", 0), self.hardware.events)
        self.assertIn("Firmware Auto unavailable", self.control.status()["notice"])

    def test_failed_fallback_is_visible(self):
        self.hardware.failed.update({("pwm1_enable", 2), ("pwm1_enable", 1)})
        self.control.fail("fixture write failure")
        self.assertIn("safety fallback failed", self.control.error)

    def test_failed_rescue_does_not_starve_kernel_watchdog(self):
        self.set_manual()
        self.hardware.failed.update({("pwm1_enable", 2), ("pwm1", 255)})
        self.hardware.temp = None
        self.control.tick()
        events = list(self.hardware.events)
        for _ in range(100):
            self.now += 2
            self.control.tick()
            self.control.request({"command": "heartbeat"})
        self.assertEqual(self.hardware.events, events)
        self.assertTrue(self.control.fault)
        self.assertIn("safety fallback failed", self.control.error)

    def test_all_curve_steps_and_safety_floor(self):
        for temperature, level in [(35000, 3), (40000, 3), (55000, 3), (65000, 5), (75000, 6), (85000, 7)]:
            with self.subTest(temperature=temperature):
                self.hardware.temp = temperature
                result = self.control.request({"command": "set", "settings": {"mode": "curve"}})
                self.assertTrue(result["ok"])
                self.assertEqual(self.hardware.values["pwm1"], level * 255 // 7)

    def test_bad_settings_do_not_mutate_state_or_refresh_heartbeat(self):
        self.set_manual()
        before = copy.deepcopy(self.control.state)
        for value in [True, None, {}, [], "30", 1.5, -1, 0, 29, 101, float("inf")]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.control.request({"command": "set", "settings": {"mode": "curve", "manual_percent": value}})
            self.assertEqual(self.control.state, before)
            self.assertEqual(self.control.last_heartbeat, 100)

    def test_curve_rejects_all_malformed_shapes(self):
        candidates = [None, {}, [], app.DEFAULT_CURVE[:2], [[40, 30]] * 5,
                      [[30, 29], [40, 40], [50, 60], [60, 80], [70, 100]],
                      [[40, 30], [55, 20], [65, 60], [75, 80], [85, 100]],
                      [[40, 30], [55, 40], [65, 60], [75, 80], [86, 100]],
                      [[40, 30], [55, 40], [65, 60], [75, 80], [85, 99]],
                      [[40, 30, 1], *app.DEFAULT_CURVE[1:]],
                      [[True, 30], *app.DEFAULT_CURVE[1:]]]
        for curve in candidates:
            with self.subTest(curve=curve):
                self.assertFalse(app.valid_curve(curve))

    def test_only_fixed_protocol_fields_are_allowed(self):
        for request in [{"command": "exec"}, {"command": "status", "path": "/etc/passwd"}, {"command": "set", "settings": {"path": "elsewhere"}}, {"command": "set"}]:
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.control.request(request)

    def test_status_does_not_keep_manual_control_alive(self):
        self.set_manual()
        self.now += 10
        self.control.request({"command": "status"})
        self.assertEqual(self.control.last_heartbeat, 100)


class ProtocolTests(unittest.TestCase):
    def test_startup_sensor_gap_keeps_daemon_available_for_recovery(self):
        hw = Hardware()
        hw.temp = None
        runtime = MagicMock()
        runtime.lstat.return_value = os.stat_result((stat.S_IFDIR | 0o755, 0, 0, 1, 0, 0, 0, 0, 0, 0))
        listener = MagicMock()
        with patch.object(app.os, "geteuid", return_value=0), \
             patch.object(app, "read_config", return_value={"uid": 1000, "gid": 1000}), \
             patch.object(app, "Hardware", return_value=hw), \
             patch.object(app, "Path") as path, \
             patch.object(app.socket, "socket") as factory, \
             patch.object(app.os, "chmod"), patch.object(app.os, "chown"), \
             patch.object(app.signal, "signal"), \
             patch.object(app.select, "select", side_effect=RuntimeError("test loop reached")):
            path.return_value.parent = runtime
            factory.return_value.__enter__.return_value = listener
            with self.assertRaisesRegex(RuntimeError, "test loop reached"):
                app.serve()
        listener.listen.assert_called_once_with(4)
        self.assertEqual(hw.values["pwm1_enable"], 2)

    def test_idle_wait_follows_the_poll_interval(self):
        seen = []

        def capture(reads, writes, errors, timeout):
            seen.append((len(reads), timeout))
            raise RuntimeError("test loop reached")

        hw = Hardware()
        runtime = MagicMock()
        runtime.lstat.return_value = os.stat_result((stat.S_IFDIR | 0o755, 0, 0, 1, 0, 0, 0, 0, 0, 0))
        listener = MagicMock()
        with patch.object(app.os, "geteuid", return_value=0), \
             patch.object(app, "read_config", return_value={"uid": 1000, "gid": 1000}), \
             patch.object(app, "Hardware", return_value=hw), \
             patch.object(app, "Path") as path, \
             patch.object(app.socket, "socket") as factory, \
             patch.object(app.os, "chmod"), patch.object(app.os, "chown"), \
             patch.object(app.signal, "signal"), \
             patch.object(app.select, "select", side_effect=capture):
            path.return_value.parent = runtime
            factory.return_value.__enter__.return_value = listener
            with self.assertRaisesRegex(RuntimeError, "test loop reached"):
                app.serve()
        self.assertEqual(seen[0][0], 2)
        self.assertGreater(seen[0][1], 1.0)
        self.assertLessEqual(seen[0][1], app.POLL_SECONDS)

    def test_json_rejects_duplicates_nonfinite_nested_nonobjects_and_large_data(self):
        for raw in [b'{"command":"status","command":"set"}', b'{"x":NaN}', b'{"x":1e999}', b'[]', b'null', b'\xff', b'{"x":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}', b'x' * 4097]:
            with self.subTest(raw=raw[:30]), self.assertRaises(ValueError):
                app.decode_message(raw)

    def test_real_unix_socket_same_user_request(self):
        first, second = socket.socketpair()
        control = app.Controller(Hardware())
        worker = threading.Thread(target=app.handle_connection, args=(second, control, os.getuid()))
        worker.start()
        with first:
            first.sendall(b'{"command":"set","settings":{"mode":"manual"}}\n')
            response = app.receive_message(first, 1)
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertTrue(response["ok"])
        self.assertEqual(response["mode"], "manual")

    def test_wrong_peer_uid_is_rejected_before_reading_request(self):
        first, second = socket.socketpair()
        control = app.Controller(Hardware())
        with first:
            app.handle_connection(second, control, os.getuid() + 1)
            self.assertEqual(first.recv(100), b"")
        self.assertIsNone(control.last_heartbeat)

    def test_slow_sender_has_total_deadline(self):
        first, second = socket.socketpair()
        with first, second:
            first.sendall(b'{"command":')
            start = time.monotonic()
            with self.assertRaises(TimeoutError):
                app.receive_message(second, 0.05)
            self.assertLess(time.monotonic() - start, 0.5)

    def test_oversized_socket_input_is_rejected(self):
        first, second = socket.socketpair()
        with first, second:
            first.sendall(b"x" * 4097)
            with self.assertRaises(ValueError):
                app.receive_message(second, 1)

    def test_trailing_request_is_rejected(self):
        first, second = socket.socketpair()
        with first, second:
            first.sendall(b'{"command":"status"}\n{}\n')
            with self.assertRaises(ValueError):
                app.receive_message(second, 1)

    def test_missing_daemon_set_is_failure_and_does_not_write_hardware(self):
        with patch.object(app, "client_request", side_effect=OSError), patch.object(app, "Hardware", return_value=Hardware()) as factory, patch("builtins.print"):
            self.assertEqual(app.client_main(["set", '{"mode":"manual"}']), 1)
            self.assertEqual(factory.return_value.events, [])

    def test_readonly_status_without_daemon(self):
        with patch.object(app, "Hardware", return_value=Hardware()) as factory:
            result = app.offline_status()
            self.assertFalse(result["control_enabled"])
            self.assertFalse(result["service"])
            self.assertEqual(result["rpm"], 2400)
            self.assertEqual(factory.return_value.events, [])

    def test_config_symlink_and_fifo_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            regular = root / "regular"
            regular.write_text('{"uid":1000,"gid":1000}')
            (root / "link").symlink_to(regular)
            os.mkfifo(root / "fifo")
            for path in (root / "link", root / "fifo"):
                with self.assertRaises((OSError, ValueError)):
                    app.read_config(path)

    def test_config_rejects_insecure_mode_and_bad_uid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config"
            path.write_text('{"uid":0,"gid":1000}')
            actual = path.stat()
            private_root = os.stat_result((stat.S_IFREG | 0o600, actual.st_ino, actual.st_dev, 1, 0, 0, actual.st_size, 0, 0, 0))
            with patch.object(app.os, "fstat", return_value=private_root), self.assertRaises(ValueError):
                app.read_config(path)
            insecure = os.stat_result((stat.S_IFREG | 0o644, actual.st_ino, actual.st_dev, 1, 0, 0, actual.st_size, 0, 0, 0))
            with patch.object(app.os, "fstat", return_value=insecure), self.assertRaises(ValueError):
                app.read_config(path)

    def test_config_rejects_oversized_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config"
            path.write_text('{"uid":1000,"gid":1000}\n')
            actual = path.stat()
            huge = os.stat_result((stat.S_IFREG | 0o600, actual.st_ino, actual.st_dev, 1, 0, 0, app.MAX_MESSAGE + 1, 0, 0, 0))
            with patch.object(app.os, "fstat", return_value=huge), self.assertRaisesRegex(ValueError, "too large"):
                app.read_config(path)

    def test_invalid_curve_reports_the_validation_error(self):
        with patch("builtins.print") as printed:
            code = app.client_main(["set", '{"mode":"curve","curve":[[40,30]]}'])
        self.assertEqual(code, 1)
        message = printed.call_args[0][0]
        self.assertIn("Curve", message)
        self.assertNotIn("/", message)

    def test_untrusted_socket_is_a_hard_failure(self):
        with patch.object(app, "client_request", side_effect=ValueError("Daemon is not root-owned")), patch("builtins.print") as printed:
            self.assertEqual(app.client_main(["status"]), 1)
        self.assertIn("untrusted", printed.call_args[0][0])

    def test_untrusted_peer_receives_no_request_bytes(self):
        if os.geteuid() == 0:
            self.skipTest("a root peer is the trusted daemon identity")
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "sock")
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(path)
            server.listen(1)
            received = []

            def accept():
                connection, _ = server.accept()
                connection.settimeout(0.5)
                try:
                    received.append(connection.recv(100))
                except OSError:
                    received.append(b"unread")
                connection.close()

            worker = threading.Thread(target=accept)
            worker.start()
            with self.assertRaisesRegex(ValueError, "not root-owned"):
                app.client_request({"command": "set", "settings": {"mode": "manual"}}, path)
            worker.join(1)
            server.close()
        self.assertFalse(worker.is_alive())
        self.assertEqual(received, [b""])

    def test_isolated_client_entry_prints_status(self):
        result = subprocess.run(
            [sys.executable, "-I", str(Path(app.__file__).resolve()), "status"],
            check=False, capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertIn("cpu_temperature", parsed)
        self.assertFalse(parsed["service"])

    def test_cli_wrapper_reexecs_isolated_status(self):
        result = subprocess.run(
            [sys.executable, str(Path(app.__file__).resolve().parent / "fanctl.py"), "status"],
            check=False, capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cpu_temperature", json.loads(result.stdout))


def write_hwmon(root, class_name, device, name, temps):
    device.mkdir(parents=True, exist_ok=True)
    (device / "name").write_text(name + "\n")
    for leaf, value in temps.items():
        target = device / leaf
        if isinstance(value, Path):
            target.symlink_to(value)
        else:
            target.write_text(str(value) + "\n")
    link_dir = root / "class/hwmon"
    link_dir.mkdir(parents=True, exist_ok=True)
    link = link_dir / class_name
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(device)


class SysfsHardwareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_thinkpad_temp_and_hottest_cpu_sensor_only(self):
        write_hwmon(self.root, "hwmon0", self.root / "devices/platform/thinkpad_hwmon/hwmon/hwmon0", "thinkpad", {"temp1_input": 45000})
        write_hwmon(self.root, "hwmon1", self.root / "devices/platform/coretemp.0/hwmon/hwmon1", "coretemp", {"temp1_input": 70000, "temp2_input": 96000})
        write_hwmon(self.root, "hwmon2", self.root / "devices/pci0000:00/nvme/hwmon/hwmon2", "nvme", {"temp1_input": 120000})
        hardware = app.Hardware(self.root)
        self.assertEqual(hardware.temperature(), 45000)
        self.assertEqual(hardware.cpu_temperature(), 96000)
        self.assertTrue(str(hardware.root).endswith("thinkpad_hwmon/hwmon/hwmon0"))

    def test_ignores_a_thinkpad_name_outside_the_platform_device(self):
        write_hwmon(self.root, "hwmon0", self.root / "devices/virtual/hwmon/hwmon0", "thinkpad", {"temp1_input": 45000})
        hardware = app.Hardware(self.root)
        self.assertFalse(hardware.available)
        self.assertIsNone(hardware.temperature())

    def test_implausible_and_symlink_cpu_inputs_are_ignored(self):
        outside = self.root / "outside-reading"
        outside.write_text("99000\n")
        cpu = self.root / "devices/platform/coretemp.0/hwmon/hwmon1"
        write_hwmon(self.root, "hwmon1", cpu, "coretemp", {"temp1_input": 200000, "temp2_input": outside, "temp3_input": 64000})
        hardware = app.Hardware(self.root)
        self.assertEqual(hardware.cpu_temperature(), 64000)

    def test_k10temp_is_a_trusted_cpu_sensor(self):
        write_hwmon(self.root, "hwmon1", self.root / "devices/pci0000:00/k10temp/hwmon/hwmon1", "k10temp", {"temp1_input": 88000})
        self.assertEqual(app.Hardware(self.root).cpu_temperature(), 88000)

    def test_cpu_sensor_rebinds_with_the_thinkpad_device(self):
        write_hwmon(self.root, "hwmon0", self.root / "devices/platform/thinkpad_hwmon/hwmon/hwmon0", "thinkpad", {"temp1_input": 40000})
        hardware = app.Hardware(self.root)
        self.assertIsNone(hardware.cpu_temperature())
        write_hwmon(self.root, "hwmon1", self.root / "devices/platform/coretemp.0/hwmon/hwmon1", "coretemp", {"temp1_input": 91000})
        self.assertIsNone(hardware.cpu_temperature())
        shutil.rmtree(self.root / "devices")
        shutil.rmtree(self.root / "class")
        write_hwmon(self.root, "hwmon3", self.root / "devices/platform/thinkpad_hwmon/hwmon/hwmon3", "thinkpad", {"temp1_input": 42000})
        write_hwmon(self.root, "hwmon4", self.root / "devices/platform/coretemp.0/hwmon/hwmon4", "coretemp", {"temp1_input": 93000})
        self.assertEqual(hardware.temperature(), 42000)
        self.assertEqual(hardware.cpu_temperature(), 93000)

    def test_cpu_sensor_arriving_later_is_used_on_the_next_poll(self):
        write_hwmon(self.root, "hwmon0", self.root / "devices/platform/thinkpad_hwmon/hwmon/hwmon0", "thinkpad", {"temp1_input": 40000})
        start = time.monotonic()
        with patch.object(app.time, "monotonic", return_value=start):
            hardware = app.Hardware(self.root)
        write_hwmon(self.root, "hwmon1", self.root / "devices/platform/coretemp.0/hwmon/hwmon1", "coretemp", {"temp1_input": 91000})
        with patch.object(app.time, "monotonic", return_value=start + app.POLL_SECONDS + 0.001):
            self.assertEqual(hardware.cpu_temperature(), 91000)

    def test_renamed_hwmon_reading_is_not_used_as_cpu_temperature(self):
        cpu = self.root / "devices/platform/coretemp.0/hwmon/hwmon1"
        write_hwmon(self.root, "hwmon1", cpu, "coretemp", {"temp1_input": 64000})
        hardware = app.Hardware(self.root)
        self.assertEqual(hardware.cpu_temperature(), 64000)
        (cpu / "name").write_text("nvme\n")
        (cpu / "temp1_input").write_text("120000\n")
        write_hwmon(self.root, "hwmon4", self.root / "devices/platform/coretemp.0/hwmon/hwmon4", "coretemp", {"temp1_input": 96000})
        self.assertEqual(hardware.cpu_temperature(), 96000)

    def test_rebinds_when_the_hwmon_node_disappears(self):
        write_hwmon(self.root, "hwmon0", self.root / "devices/platform/thinkpad_hwmon/hwmon/hwmon0", "thinkpad", {"temp1_input": 40000})
        hardware = app.Hardware(self.root)
        self.assertEqual(hardware.temperature(), 40000)
        shutil.rmtree(self.root / "devices")
        shutil.rmtree(self.root / "class")
        write_hwmon(self.root, "hwmon3", self.root / "devices/platform/thinkpad_hwmon/hwmon/hwmon3", "thinkpad", {"temp1_input": 51000})
        self.assertEqual(hardware.temperature(), 51000)

    def test_control_and_watchdog_stay_inside_the_supplied_sysfs(self):
        write_hwmon(self.root, "hwmon0", self.root / "devices/platform/thinkpad_hwmon/hwmon/hwmon0", "thinkpad", {"temp1_input": 45000, "pwm1_enable": 2, "pwm1": 0})
        param = self.root / "module/thinkpad_acpi/parameters/fan_control"
        param.parent.mkdir(parents=True)
        param.write_text("Y\n")
        hardware = app.Hardware(self.root)
        self.assertTrue(hardware.control_ready())
        watchdog = self.root / "bus/platform/drivers/thinkpad_hwmon/fan_watchdog"
        watchdog.parent.mkdir(parents=True)
        self.assertTrue(hardware.watchdog(45))
        self.assertEqual(watchdog.read_text(), "45")
        self.assertTrue(hardware.write("pwm1_enable", 1))
        self.assertEqual((hardware.root / "pwm1_enable").read_text(), "1")
        self.assertFalse(hardware.write("fan_watchdog", 0))


if __name__ == "__main__":
    unittest.main()
