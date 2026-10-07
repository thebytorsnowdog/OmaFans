import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("setup_script", Path(__file__).parents[1] / "scripts/setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patches = [patch.object(setup, name, self.root / relative) for name, relative in [
            ("LIB", "lib"), ("CONFIG", "config"), ("UNIT", "units/omafans.service"), ("MODPROBE", "modprobe/omafans.conf")]]
        for item in self.patches:
            item.start()
        self.account = SimpleNamespace(pw_uid=1000, pw_gid=1000)

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def test_dry_run_changes_nothing_and_does_not_call_systemctl(self):
        with patch.object(setup.pwd, "getpwnam", return_value=self.account), patch.object(setup, "systemctl") as call, patch("builtins.print"):
            setup.install("fixture", True, True)
            setup.remove(True)
        call.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_active_conflict_prevents_any_installation(self):
        with patch.object(setup.pwd, "getpwnam", return_value=self.account), patch.object(setup, "systemctl", return_value=SimpleNamespace(returncode=0)), patch("builtins.print"), self.assertRaises(ValueError):
            setup.install("fixture", False, False)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_systemctl_failure_is_not_mistaken_for_inactive(self):
        with patch.object(setup.pwd, "getpwnam", return_value=self.account), patch.object(setup, "systemctl", return_value=SimpleNamespace(returncode=1)), patch("builtins.print"), self.assertRaises(ValueError):
            setup.install("fixture", False, False)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_root_controller_is_rejected(self):
        with patch.object(setup.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=0,pw_gid=0)), self.assertRaises(ValueError):
            setup.install("fixture", False, True)

    def test_symlink_destination_is_rejected(self):
        target = self.root / "target"
        target.write_text("preserve")
        alias = self.root / "alias"
        alias.symlink_to(target)
        with self.assertRaises(ValueError):
            setup.safe_destination(alias)
        self.assertEqual(target.read_text(), "preserve")

    def test_atomic_install_update_remove_roundtrip_in_fixture(self):
        calls = []
        def fake_systemctl(*args, **kwargs):
            calls.append(args)
            return SimpleNamespace(returncode=3 if args[0] == "is-active" else 0, stdout=b"success\n")
        def fixture_directory(path):
            path.mkdir(parents=True, exist_ok=True)
        # Ownership checks are tested separately; no root operations are used.
        with patch.object(setup.pwd, "getpwnam", return_value=self.account), patch.object(setup, "systemctl", side_effect=fake_systemctl), patch.object(setup, "safe_directory", side_effect=fixture_directory), patch.object(setup, "safe_destination"), patch("builtins.print"):
            setup.install("fixture", True, False)
            self.assertEqual((setup.LIB / "omafans.py").read_bytes(), (setup.SOURCE / "omafans.py").read_bytes())
            self.assertEqual((setup.CONFIG / "controller.json").stat().st_mode & 0o777, 0o600)
            self.assertTrue(setup.UNIT.exists())
            setup.install("fixture", True, False)
            setup.remove(False)
        for path in (setup.UNIT, setup.MODPROBE, setup.LIB, setup.CONFIG):
            self.assertFalse(path.exists())
        self.assertIn(("disable", "--now", "omafans.service"), calls)

    def test_failed_service_stop_retains_installed_files(self):
        setup.UNIT.parent.mkdir()
        setup.UNIT.write_text("fixture")
        def call(*args, **kwargs):
            return SimpleNamespace(returncode=3 if args[0] == "is-active" else 0, stdout=b"exit-code\n")
        with patch.object(setup, "safe_directory"), patch.object(setup, "safe_destination"), patch.object(setup, "systemctl", side_effect=call), patch("builtins.print"), self.assertRaises(ValueError):
            setup.remove(False)
        self.assertTrue(setup.UNIT.exists())


if __name__ == "__main__":
    unittest.main()
