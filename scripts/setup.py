#!/usr/bin/env python3
"""Explicit install/remove for the privileged component; never run by QML."""
import argparse
import json
import os
import pwd
import stat

# Only a fixed systemctl executable and fixed argument arrays are used below.
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent
LIB = Path("/usr/local/lib/omafans")
CONFIG = Path("/etc/omafans")
UNIT = Path("/etc/systemd/system/omafans.service")
MODPROBE = Path("/etc/modprobe.d/omafans.conf")
MODULES_LOAD = Path("/etc/modules-load.d/omafans.conf")
SYSFS = Path("/sys")
KERNEL_OPTION = b"# Managed by OmaFans\noptions thinkpad_acpi fan_control=1\n"
IT87_MODPROBE_OPTION = b"# Managed by OmaFans\noptions it87 force_id=0x8622 ignore_resource_conflict=1\n"
IT87_MODULES_LOAD = b"# Managed by OmaFans\nit87\n"
MANAGED_MODPROBE = (KERNEL_OPTION, IT87_MODPROBE_OPTION)
MANAGED_MODULES_LOAD = (IT87_MODULES_LOAD,)
CONFLICTS = ("thinkfan", "fancontrol", "nbfc", "nbfc_service", "omarchy-fanctl")


def _read_dmi(sysfs, field):
    try:
        return (sysfs / "devices/virtual/dmi/id" / field).read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return ""


def detect_profile(sysfs=None):
    root = SYSFS if sysfs is None else Path(sysfs)
    if (root / "devices/platform/thinkpad_hwmon").exists() or (root / "module/thinkpad_acpi").exists():
        return "thinkpad"
    if (root / "devices/platform/it87.2608").exists():
        return "it87"
    vendor = _read_dmi(root, "sys_vendor").upper()
    product = _read_dmi(root, "product_name").upper()
    board = _read_dmi(root, "board_name").upper()
    if vendor == "AZW" and ("MINI S" in product or "MINI S" in board):
        return "it87"
    return "thinkpad"


def systemctl(*args, check=True):
    # Callers supply literal service operations; no shell or user arguments.
    return subprocess.run(  # nosec B603
        ["/usr/bin/systemctl", *args], check=check, timeout=30,
        stdin=subprocess.DEVNULL, capture_output=True,
        env={"PATH": "/usr/bin:/bin", "LANG": "C"},
    )


def safe_directory(path):
    # All ancestors must already be trusted; never follow a redirected directory.
    for parent in reversed((path, *path.parents)):
        if not parent.exists() and not parent.is_symlink():
            parent.mkdir(mode=0o755)
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("Installation directory is not root-owned and protected")


def safe_destination(path):
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_nlink != 1:
            raise ValueError("Unsafe installation destination")


def atomic_write(path, data, mode):
    safe_directory(path.parent)
    safe_destination(path)
    fd, temporary = tempfile.mkstemp(prefix=".omafans-", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary_path = None
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def install(user, enable_kernel, dry_run, profile=None):
    account = pwd.getpwnam(user)
    if account.pw_uid == 0 or account.pw_gid == 0:
        raise ValueError("Choose an unprivileged desktop account")
    selected = detect_profile() if profile in (None, "auto") else profile
    if selected not in ("thinkpad", "it87"):
        raise ValueError("Unsupported hardware profile")
    files = {
        LIB / "omafans.py": ((SOURCE / "omafans.py").read_bytes(), 0o644),
        CONFIG / "controller.json": (json.dumps({"uid": account.pw_uid, "gid": account.pw_gid}).encode() + b"\n", 0o600),
        UNIT: ((SOURCE / "system/omafans.service").read_bytes(), 0o644),
    }
    if enable_kernel:
        if selected == "it87":
            files[MODPROBE] = (IT87_MODPROBE_OPTION, 0o644)
            files[MODULES_LOAD] = (IT87_MODULES_LOAD, 0o644)
        else:
            files[MODPROBE] = (KERNEL_OPTION, 0o644)
    print(f"Detected hardware profile: {selected}")
    for path in files:
        print(f"Install {path}")
    if dry_run:
        print("Dry run: no files or services changed")
        return
    for name in CONFLICTS:
        result = systemctl("is-active", "--quiet", name + ".service", check=False)
        if result.returncode == 0:
            raise ValueError("Another fan controller is active; disable it before installing OmaFans")
        if result.returncode not in (3, 4):
            raise ValueError("Unable to verify conflicting fan controllers")
    # Preflight every destination before changing any files.
    for path in files:
        safe_directory(path.parent)
        safe_destination(path)
    if enable_kernel and MODPROBE.exists() and MODPROBE.read_bytes() not in MANAGED_MODPROBE:
        raise ValueError("Refusing to overwrite an unmanaged modprobe file")
    if enable_kernel and MODULES_LOAD in files and MODULES_LOAD.exists() and MODULES_LOAD.read_bytes() not in MANAGED_MODULES_LOAD:
        raise ValueError("Refusing to overwrite an unmanaged modules-load file")
    active = systemctl("is-active", "--quiet", "omafans.service", check=False)
    if active.returncode == 0:
        systemctl("stop", "omafans.service")
    elif active.returncode not in (3, 4):
        raise ValueError("Unable to inspect existing OmaFans service")
    for path, (data, mode) in files.items():
        atomic_write(path, data, mode)
    systemctl("daemon-reload")
    systemctl("enable", "omafans.service")
    print("Installed. Start omafans.service explicitly after reviewing setup and hardware compatibility.")
    if enable_kernel:
        if selected == "it87":
            print("Kernel module configuration installed for it87.")
        else:
            print("Kernel option installed. Reboot to apply; do not unload the driver on a running laptop.")


def remove(dry_run):
    paths = (UNIT, CONFIG / "controller.json", LIB / "omafans.py", MODPROBE, MODULES_LOAD)
    for path in paths:
        print(f"Remove if managed: {path}")
    if dry_run:
        print("Dry run: no files or services changed")
        return
    for path in paths:
        if path.parent.exists():
            safe_directory(path.parent)
        safe_destination(path)
    if MODPROBE.exists() and MODPROBE.read_bytes() not in MANAGED_MODPROBE:
        raise ValueError("Refusing to remove an unmanaged modprobe file")
    if MODULES_LOAD.exists() and MODULES_LOAD.read_bytes() not in MANAGED_MODULES_LOAD:
        raise ValueError("Refusing to remove an unmanaged modules-load file")
    if UNIT.exists():
        systemctl("disable", "--now", "omafans.service")
        status = systemctl("is-active", "--quiet", "omafans.service", check=False)
        if status.returncode not in (3, 4):
            raise ValueError("Cannot verify daemon stopped; files retained")
        # ExecStopPost must have returned control successfully.
        result = systemctl("show", "omafans.service", "--property=Result", "--value")
        if result.stdout.strip() != b"success":
            raise ValueError("Service stop reported a failure; files retained for recovery")
    for path in paths:
        path.unlink(missing_ok=True)
    for path in (LIB, CONFIG):
        if path.exists() and not any(path.iterdir()):
            path.rmdir()
    systemctl("daemon-reload")
    print("Removed the system component. Reboot to clear its kernel option; remove the shell plugin separately.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "remove"))
    parser.add_argument("--user", help="Desktop account allowed to control the fan (required for install)")
    parser.add_argument("--enable-kernel-control", action="store_true")
    parser.add_argument("--profile", choices=("auto", "thinkpad", "it87"), default="auto")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.action == "install" and not args.user:
        parser.error("install requires --user")
    if args.action == "remove" and (args.user or args.enable_kernel_control or args.profile != "auto"):
        parser.error("remove accepts only --dry-run")
    if not args.dry_run and os.geteuid() != 0:
        parser.error("Run the reviewed setup script as root, or use --dry-run")
    try:
        if args.action == "install":
            install(args.user, args.enable_kernel_control, args.dry_run, args.profile)
        else:
            remove(args.dry_run)
        return 0
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
