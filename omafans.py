#!/usr/bin/env python3
"""OmaFans local protocol and privileged ThinkPad controller (stdlib only).

The installed daemon is run with Python isolated mode. It never imports the
user's plugin code, reads user state files, or accepts paths/commands over IPC.
"""

import argparse
import glob
import json
import math
import os
import select
import signal
import socket
import stat
import struct
import sys
import time
from pathlib import Path

SOCKET_PATH = "/run/omafans/control.sock"
CONFIG_PATH = "/etc/omafans/controller.json"
FAN_CONTROL_PARAM = "/sys/module/thinkpad_acpi/parameters/fan_control"
WATCHDOG_PATH = "/sys/bus/platform/drivers/thinkpad_hwmon/fan_watchdog"
MAX_MESSAGE = 4096
IO_TIMEOUT = 0.25
CLIENT_TIMEOUT = 2.0
HEARTBEAT_TIMEOUT = 15.0
WATCHDOG_SECONDS = 45
POLL_SECONDS = 2.0
OVERHEAT_MC = 92000
DEFAULT_CURVE = [[40, 30], [55, 40], [65, 60], [75, 80], [85, 100]]


def default_state():
    return {"mode": "auto", "manual_percent": 60,
            "curve": [list(row) for row in DEFAULT_CURVE]}


def heartbeat_clock():
    # Unlike CLOCK_MONOTONIC, Linux BOOTTIME includes time spent suspended.
    return time.clock_gettime(time.CLOCK_BOOTTIME)


def valid_curve(curve):
    if not isinstance(curve, list) or len(curve) != 5:
        return False
    previous_temp, previous_percent = 29, 30
    for point in curve:
        if not isinstance(point, list) or len(point) != 2:
            return False
        temp, percent = point
        if type(temp) is not int or type(percent) is not int:
            return False
        if not previous_temp < temp <= 85 or not previous_percent <= percent <= 100:
            return False
        previous_temp, previous_percent = temp, percent
    return previous_percent == 100


def validate_update(payload, previous):
    if not isinstance(payload, dict) or not payload:
        raise ValueError("Expected a nonempty settings object")
    if set(payload) - {"mode", "manual_percent", "curve"}:
        raise ValueError("Unknown setting")
    state = dict(previous)
    if "mode" in payload:
        if payload["mode"] not in ("auto", "manual", "curve"):
            raise ValueError("Invalid mode")
        state["mode"] = payload["mode"]
    if "manual_percent" in payload:
        value = payload["manual_percent"]
        if type(value) is not int or not 30 <= value <= 100:
            raise ValueError("Manual percentage must be an integer from 30 to 100")
        state["manual_percent"] = value
    if "curve" in payload:
        if not valid_curve(payload["curve"]):
            raise ValueError("Curve needs five rising temperatures (30–85), nondecreasing percentages (30–100), ending at 100")
        state["curve"] = [list(row) for row in payload["curve"]]
    return state


def decode_message(raw):
    if len(raw) > MAX_MESSAGE:
        raise ValueError("Message too large")
    def reject_constant(value):
        raise ValueError("Non-finite JSON number")
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    try:
        value = json.loads(raw, parse_constant=reject_constant,
                           object_pairs_hook=unique_object)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")  # noqa: TRY004 - protocol errors are ValueError
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 8:
            raise ValueError("JSON nesting is too deep")
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("Non-finite JSON number")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return value


def encode_message(value):
    raw = json.dumps(value, allow_nan=False, separators=(",", ":")).encode() + b"\n"
    if len(raw) > MAX_MESSAGE:
        raise ValueError("Message too large")
    return raw


def receive_message(connection, timeout):
    # A total deadline prevents a slow peer extending the timeout byte by byte.
    deadline = time.monotonic() + timeout
    raw = bytearray()
    while b"\n" not in raw:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Request deadline exceeded")
        connection.settimeout(remaining)
        chunk = connection.recv(min(1024, MAX_MESSAGE + 1 - len(raw)))
        if not chunk:
            raise ValueError("Incomplete message")
        raw.extend(chunk)
        if len(raw) > MAX_MESSAGE:
            raise ValueError("Message too large")
    line, tail = raw.split(b"\n", 1)
    if tail.strip():
        raise ValueError("One request per connection")
    return decode_message(line)


def read_number(path):
    try:
        with open(path, encoding="ascii") as stream:
            return int(stream.read(64).strip())
    except (OSError, ValueError, UnicodeError):
        return None


class Hardware:
    """Only the modern thinkpad_hwmon device is allowed to receive writes."""

    def __init__(self):
        self.root = None
        for name in sorted(glob.glob("/sys/class/hwmon/hwmon*/name")):
            try:
                path = Path(name).parent.resolve(strict=True)
                if (path.is_relative_to("/sys/devices/platform/thinkpad_hwmon/hwmon")
                        and Path(name).read_text(encoding="ascii").strip() == "thinkpad"):
                    self.root = path
                    break
            except (OSError, UnicodeError):
                continue

    @property
    def available(self):
        return self.root is not None

    def control_ready(self):
        try:
            return self.available and Path(FAN_CONTROL_PARAM).read_text().strip().lower() in ("1", "y")
        except OSError:
            return False

    def read(self, name):
        return read_number(self.root / name) if self.root else None

    def temperature(self):
        # temp1 is required. Disconnected or implausible readings fail closed.
        value = self.read("temp1_input")
        return value if value is not None and 0 <= value <= 125000 else None

    def write(self, name, value):
        if not self.root or name not in ("pwm1", "pwm1_enable"):
            return False
        return self._write(self.root / name, value)

    @staticmethod
    def _write(path, value):
        try:
            with open(path, "w", encoding="ascii") as stream:
                stream.write(str(value))
            return True
        except OSError:
            return False

    def watchdog(self, seconds):
        return self._write(WATCHDOG_PATH, seconds)


class Controller:
    def __init__(self, hardware, clock=heartbeat_clock):
        self.hardware = hardware
        self.clock = clock
        self.state = default_state()
        self.last_heartbeat = None
        self.error = ""
        self.notice = ""
        self.fault = False

    def safe(self):
        """Firmware auto, or highest normal speed if auto is unsupported.

        Never disarm the watchdog until automatic mode is read back. Never
        claim a fallback succeeded just because it was attempted.
        """
        hw = self.hardware
        self.state["mode"] = "auto"
        if hw.write("pwm1_enable", 2) and hw.read("pwm1_enable") == 2:
            self.notice = ""
            return hw.watchdog(0)
        self.notice = "Firmware Auto unavailable; highest normal fan speed requested"
        armed = hw.watchdog(WATCHDOG_SECONDS)
        enabled = hw.write("pwm1_enable", 1)
        full = hw.write("pwm1", 255) if enabled else False
        return armed and enabled and full and hw.read("pwm1") == 255

    def fail(self, message):
        self.fault = True
        self.error = message
        if not self.safe():
            self.error += "; safety fallback failed"
        return False

    def tick(self):
        hw = self.hardware
        if self.fault:
            # Do not re-arm or write here: a failed rescue must let the kernel
            # watchdog expire. The service has no automatic restart loop.
            return False
        if not hw.control_ready():
            return self.fail("Kernel fan control is unavailable")
        temperature = hw.temperature()
        age = None if self.last_heartbeat is None else self.clock() - self.last_heartbeat
        if temperature is None:
            return self.fail("Temperature sensor unavailable")
        if temperature >= OVERHEAT_MC:
            target = 100
            self.state["mode"] = "auto"
            self.error = "High temperature: highest normal fan speed requested"
        elif age is None or not 0 <= age <= HEARTBEAT_TIMEOUT or self.state["mode"] == "auto":
            self.error = ""
            if not self.safe():
                return self.fail("Unable to restore automatic fan control")
            return True
        else:
            self.error = ""
            self.notice = ""
            target = self.state["manual_percent"]
            if self.state["mode"] == "curve":
                target = self.state["curve"][0][1]
                for threshold, percent in self.state["curve"]:
                    if temperature >= threshold * 1000:
                        target = percent
        # Arm before manual mode, including before an overheat override.
        if not hw.watchdog(WATCHDOG_SECONDS):
            return self.fail("Fan watchdog could not be armed")
        level = max(2, min(7, math.ceil(target * 7 / 100)))
        pwm = level * 255 // 7
        if not hw.write("pwm1_enable", 1) or not hw.write("pwm1", pwm):
            return self.fail("Fan write failed")
        if hw.read("pwm1_enable") != 1 or hw.read("pwm1") != pwm:
            return self.fail("Fan write verification failed")
        return True

    def status(self):
        hw = self.hardware
        pwm, enable = hw.read("pwm1"), hw.read("pwm1_enable")
        temp = hw.temperature()
        return {**self.state, "available": hw.available, "service": True,
                "control_enabled": hw.control_ready() and not self.fault,
                "rpm": hw.read("fan1_input"),
                "percent": round(pwm * 100 / 255) if pwm is not None and enable == 1 else None,
                "temperature": temp / 1000 if temp is not None else None,
                "error": self.error, "notice": self.notice}

    def request(self, request):
        command = request.get("command")
        if command not in ("status", "heartbeat", "set"):
            raise ValueError("Unknown command")
        allowed = {"command", "settings"} if command == "set" else {"command"}
        if set(request) - allowed:
            raise ValueError("Unknown request field")
        if command == "set":
            state = validate_update(request.get("settings"), self.state)
            if self.fault:
                return {**self.status(), "ok": False}
            self.state = state
        if command in ("heartbeat", "set"):
            if command == "heartbeat" and self.last_heartbeat is not None:
                age = self.clock() - self.last_heartbeat
                if not 0 <= age <= HEARTBEAT_TIMEOUT:
                    self.state["mode"] = "auto"
            self.last_heartbeat = self.clock()
        good = self.tick() if command == "set" else not self.fault
        return {**self.status(), "ok": good}


def read_config(path=CONFIG_PATH):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or info.st_nlink != 1:
            raise ValueError("Controller configuration must be a private root-owned regular file")
        config = decode_message(os.read(fd, MAX_MESSAGE + 1))
    finally:
        os.close(fd)
    if set(config) != {"uid", "gid"} or any(type(v) is not int or v <= 0 for v in config.values()):
        raise ValueError("Invalid controller UID/GID")
    return config


def handle_connection(connection, controller, allowed_uid):
    with connection:
        try:
            credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            _, uid, _ = struct.unpack("3i", credentials)
            if uid != allowed_uid:
                return
            request = receive_message(connection, IO_TIMEOUT)
            response = controller.request(request)
        except (ValueError, OSError):
            response = {"ok": False, "error": "Invalid or incomplete request"}
        try:
            connection.settimeout(IO_TIMEOUT)
            connection.sendall(encode_message(response))
        except OSError:
            return


def serve():
    if os.geteuid() != 0:
        raise ValueError("The daemon must be started by its system service")
    config = read_config()
    hw = Hardware()
    if not hw.control_ready():
        raise ValueError("Compatible ThinkPad hardware and fan_control=1 are required")
    runtime = Path(SOCKET_PATH).parent
    info = runtime.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError("Unsafe runtime directory")
    controller = Controller(hw)
    if not controller.tick():
        raise ValueError(controller.error)
    running = True
    def stop(signum, frame):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        # systemd owns this private, root-writable runtime directory.
        Path(SOCKET_PATH).unlink(missing_ok=True)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(SOCKET_PATH)
            # The root-owned parent prevents socket replacement. Only the
            # selected user can connect; SO_PEERCRED independently authenticates
            # both ends even if that trusted user changes the inode's mode.
            # Set the mode while still owner: the service deliberately lacks
            # CAP_FOWNER after ownership is transferred to the desktop user.
            os.chmod(SOCKET_PATH, 0o600)
            os.chown(SOCKET_PATH, config["uid"], config["gid"])
            listener.listen(4)
            next_tick = time.monotonic()
            while running:
                now = time.monotonic()
                if now >= next_tick:
                    controller.tick()
                    next_tick = time.monotonic() + POLL_SECONDS
                readable, _, _ = select.select([listener], [], [], min(0.25, max(0, next_tick - time.monotonic())))
                if readable:
                    connection, _ = listener.accept()
                    handle_connection(connection, controller, config["uid"])
    finally:
        safe = controller.safe()
        Path(SOCKET_PATH).unlink(missing_ok=True)
        if not safe:
            print("OmaFans: safety fallback failed during shutdown", file=sys.stderr)
    return 0 if safe else 1


def offline_status():
    hw = Hardware()
    result = Controller(hw).status()
    result.update(service=False, control_enabled=False, mode="auto", error="",
                  notice="OmaFans daemon unavailable; monitoring only")
    enable = hw.read("pwm1_enable")
    if enable == 1:
        result["mode"] = "manual"
    return result


def client_request(request, path=SOCKET_PATH):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(CLIENT_TIMEOUT)
        connection.connect(path)
        # Prevent a replaced, unprivileged local socket impersonating the daemon.
        credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _, uid, _ = struct.unpack("3i", credentials)
        if uid != 0:
            raise ValueError("Daemon is not root-owned")
        connection.sendall(encode_message(request))
        return receive_message(connection, CLIENT_TIMEOUT)


def client_main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    command = args[0] if args else "status"
    try:
        if command not in ("status", "heartbeat", "set") or len(args) > (2 if command == "set" else 1):
            raise ValueError("Use status, heartbeat, or set JSON")
        request = {"command": command}
        if command == "set":
            payload = decode_message((args[1] if len(args) == 2 else "{}").encode())
            validate_update(payload, default_state())
            request["settings"] = payload
        try:
            response = client_request(request)
        except (OSError, ValueError):
            response = offline_status()
            response["ok"] = command != "set"
            if command == "set":
                response["error"] = "Control unavailable; settings were not applied"
        print(encode_message(response).decode(), end="")
        return 0 if response.get("ok", True) else 1
    except (ValueError, OSError):
        print('{"ok":false,"error":"Invalid request"}')
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("serve", "release"))
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise ValueError("Root privileges required for the system daemon")
        if args.command == "release":
            hw = Hardware()
            return 0 if not hw.available or Controller(hw).safe() else 1
        return serve()
    except (ValueError, OSError) as exc:
        print(f"OmaFans: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
