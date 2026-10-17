#!/usr/bin/env python3
"""Unprivileged CLI. Isolated mode keeps user-site packages out of the client."""
import os
import sys


def main():
    # Fixed re-exec of the adjacent controller client. No shell and no chosen executable.
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "omafans.py")
    os.execv(sys.executable, [sys.executable, "-I", script, *sys.argv[1:]])  # nosec B606


if __name__ == "__main__":
    raise SystemExit(main())
