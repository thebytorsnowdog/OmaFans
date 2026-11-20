import contextlib
import io
import unittest
from unittest.mock import patch

import omafans as app
from test_controller import Hardware


class OmaFansSafetyTests(unittest.TestCase):
    def setUp(self):
        self.hardware = Hardware()
        self.now = 100.0
        self.control = app.Controller(self.hardware, lambda: self.now)

    def set(self, **settings):
        return self.control.request({"command": "set", "settings": settings})

    def test_failed_auto_write_preserves_verified_firmware_auto(self):
        self.hardware.failed.update({("pwm1_enable", 2), ("watchdog", 45), ("pwm1", 255)})
        result = self.set(mode="auto")
        self.assertTrue(result["ok"])
        self.assertTrue(result["firmware_auto"])
        self.assertIn("existing Auto confirmed", result["notice"])
        self.assertEqual(self.hardware.events, [("pwm1_enable", 2), ("watchdog", 0)])

    def test_failed_auto_and_watchdog_never_attempt_manual_writes(self):
        for auto_write_ok in (False, True):
            for speed_write_ok in (False, True):
                with self.subTest(auto_write_ok=auto_write_ok, speed_write_ok=speed_write_ok):
                    hw = Hardware()
                    control = app.Controller(hw, lambda: self.now)
                    hw.values.update(pwm1_enable=1, pwm1=109)
                    hw.failed.add(("watchdog", 45))
                    if not speed_write_ok:
                        hw.failed.add(("pwm1", 255))

                    def write(name, value):
                        if (name, value) == ("pwm1_enable", 2):
                            hw.events.append((name, value))
                            return auto_write_ok  # Auto read-back stays in the prior mode.
                        return Hardware.write(hw, name, value)

                    with patch.object(hw, "write", side_effect=write), contextlib.redirect_stderr(io.StringIO()):
                        result = control.request({"command": "set", "settings": {"mode": "auto"}})
                    self.assertFalse(result["ok"])
                    self.assertFalse(result["control_enabled"])
                    self.assertFalse(result["firmware_auto"])
                    self.assertEqual(hw.values["pwm1_enable"], 1)
                    self.assertEqual(hw.values["pwm1"], 109)
                    self.assertEqual(hw.events, [("pwm1_enable", 2), ("watchdog", 45)])
                    expected = "read-back failed" if auto_write_ok else "write failed"
                    self.assertIn(expected, result["error"])
                    self.assertIn("watchdog arm failed; manual writes skipped", result["error"])
                    self.assertIn("manual mode observed", result["notice"])

    def test_watchdog_backed_fallback_reports_each_write_outcome(self):
        for failed_write, expected, ok in (
            (("pwm1_enable", 1), "manual mode write failed", False),
            (("pwm1", 255), "highest normal speed write failed", False),
            (None, "manual mode and highest normal speed confirmed", True),
        ):
            with self.subTest(failed_write=failed_write):
                hw = Hardware()
                control = app.Controller(hw, lambda: self.now)
                hw.values.update(pwm1_enable=1, pwm1=109)
                hw.failed.add(("pwm1_enable", 2))
                if failed_write is not None:
                    hw.failed.add(failed_write)
                with contextlib.redirect_stderr(io.StringIO()):
                    result = control.request({"command": "set", "settings": {"mode": "auto"}})
                self.assertIs(result["ok"], ok)
                self.assertFalse(result["firmware_auto"])
                self.assertEqual(result["mode"], "auto")
                self.assertIn("watchdog armed", result["notice"])
                self.assertIn(expected, result["notice"])
                events = [("pwm1_enable", 2), ("watchdog", 45), ("pwm1_enable", 1)]
                if failed_write != ("pwm1_enable", 1):
                    events.append(("pwm1", 255))
                self.assertEqual(hw.events, events)

    def test_fallback_requires_mode_and_speed_read_back(self):
        self.hardware.values.update(pwm1_enable=1, pwm1=109)
        self.hardware.failed.add(("pwm1_enable", 2))
        for missing in ("pwm1_enable", "pwm1"):
            with self.subTest(missing=missing):
                def read(name):
                    return None if name == missing else Hardware.read(self.hardware, name)

                with patch.object(self.hardware, "read", side_effect=read):
                    self.assertFalse(self.control.safe())
                self.assertIn("manual mode and speed writes succeeded; read-back failed", self.control.notice)

    def test_firmware_auto_disarm_failure_is_reported_without_retrying(self):
        self.hardware.failed.add(("watchdog", 0))
        with contextlib.redirect_stderr(io.StringIO()):
            result = self.set(mode="auto")
        self.assertFalse(result["ok"])
        self.assertTrue(result["firmware_auto"])
        self.assertIn("watchdog disarm failed", result["error"])
        self.assertEqual(self.hardware.events, [("pwm1_enable", 2), ("watchdog", 0)])

    def test_release_uses_the_same_watchdog_guard(self):
        self.hardware.values.update(pwm1_enable=1, pwm1=109)
        self.hardware.failed.update({("pwm1_enable", 2), ("watchdog", 45)})
        with patch.object(app, "Hardware", return_value=self.hardware), patch.object(app.os, "geteuid", return_value=0), contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(app.main(["release"]), 1)
        self.assertIn("watchdog arm failed; manual writes skipped", output.getvalue())
        self.assertEqual(self.hardware.events, [("pwm1_enable", 2), ("watchdog", 45)])

    def test_expired_settings_keep_values_in_auto_until_mode_is_selected(self):
        curve = [[40, 31], [55, 41], [65, 61], [75, 81], [85, 100]]
        for mode, elapsed in (("manual", 16), ("curve", -1)):
            with self.subTest(mode=mode, elapsed=elapsed):
                self.assertTrue(self.set(mode=mode, manual_percent=45, curve=curve)["ok"])
                self.now += elapsed  # No control tick between the old lease and this partial update.
                self.hardware.events.clear()
                for settings in ({"manual_percent": 50}, {"curve": curve}):
                    result = self.set(**settings)
                    self.assertTrue(result["ok"])
                    self.assertEqual(result["mode"], "auto")
                    self.assertTrue(result["firmware_auto"])
                    self.assertEqual(result["manual_percent"], 50)
                    self.assertEqual(result["curve"], curve)
                self.assertEqual(self.hardware.events, [("pwm1_enable", 2), ("watchdog", 0)] * 2)
                self.assertEqual(self.control.request({"command": "heartbeat"})["mode"], "auto")
                self.now += 16
                result = self.set(mode=mode)
                self.assertTrue(result["ok"])
                self.assertEqual(result["mode"], mode)
                self.assertFalse(result["firmware_auto"])
                self.assertEqual(result["manual_percent"], 50)
                self.assertEqual(result["curve"], curve)

    def test_partial_update_with_current_lease_keeps_mode(self):
        self.assertTrue(self.set(mode="manual", manual_percent=30)["ok"])
        self.now += app.HEARTBEAT_TIMEOUT
        result = self.set(manual_percent=60)
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "manual")
        self.assertEqual(result["manual_percent"], 60)
        self.assertEqual(self.control.last_heartbeat, self.now)
