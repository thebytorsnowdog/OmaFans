#!/usr/bin/env python3
"""Portable repository contract, privilege invariants, and privacy checks."""
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def check():
    errors = []
    def require(condition, message):
        if not condition:
            errors.append(message)
    for name in ("manifest.json", "Panel.qml", "Service.qml", "fanctl.py", "omafans.py", "README.md", "LICENSE", "SECURITY.md", "docs/SECURITY_REVIEW.md", "system/omafans.service", "scripts/setup.py"):
        require((ROOT / name).is_file(), f"Missing required file: {name}")
    manifest = json.loads((ROOT / "manifest.json").read_text())
    require(manifest.get("schemaVersion") == 1, "Unsupported manifest schema")
    require(manifest.get("id") == "community.omafans", "Unexpected plugin ID")
    require(manifest.get("name") == "OmaFans", "Unexpected plugin name")
    require(manifest.get("author") == "OmaFans contributors", "Use the neutral project author")
    require(manifest.get("license") == "MIT", "Manifest/license mismatch")
    require(set(manifest.get("kinds", [])) == {"bar-widget", "service"}, "Unexpected entry-point kinds")
    for key in ("barWidget", "service"):
        value = manifest.get("entryPoints", {}).get(key, "")
        path = Path(value)
        require(bool(value) and not path.is_absolute() and ".." not in path.parts and (ROOT / path).is_file(), f"Invalid entry point: {key}")
    service = (ROOT / "system/omafans.service").read_text()
    for expected in ("Restart=no", "ProtectHome=yes", "ProtectSystem=strict", "NoNewPrivileges=yes", "RestrictAddressFamilies=AF_UNIX", "ExecStart=/usr/bin/python3 -I /usr/local/lib/omafans/omafans.py serve"):
        require(expected in service, f"Missing service safety invariant: {expected}")
    source = ast.parse((ROOT / "omafans.py").read_text())
    allowed = {"argparse", "glob", "json", "math", "os", "pathlib", "select", "signal", "socket", "stat", "struct", "sys", "time"}
    for node in ast.walk(source):
        if isinstance(node, ast.Import):
            require(all(item.name in allowed for item in node.names), "Unreviewed daemon import")
        elif isinstance(node, ast.ImportFrom):
            require(node.module in allowed, "Unreviewed daemon import")
    # Scan the candidate tree, excluding only generated/local VCS artifacts.
    excluded = {".git", "__pycache__", ".venv", ".ruff_cache", "audit-results"}
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if set(relative.parts) & excluded:
            continue
        require(not path.is_symlink(), f"Symlink in public tree: {relative}")
        if not path.is_file() or path.suffix.lower() in (".png", ".jpg", ".webp"):
            continue
        try:
            text = path.read_text()
        except UnicodeError:
            errors.append(f"Unreviewed binary file: {relative}")
            continue
        require(not re.search(r"/(?:home|Users)/[A-Za-z0-9_.-]+/", text), f"Personal absolute path in {relative}")
        require(not re.search(r"local\.[a-z0-9_-]+\.fans", text), f"Legacy personal plugin ID in {relative}")
        require(not re.search(r"[\w.+-]+@(?!users\.noreply\.github\.com)[\w.-]+\.[A-Za-z]{2,}", text), f"Review email address in {relative}")
    for path in (ROOT / "omafans.py", ROOT / "fanctl.py", ROOT / "scripts/setup.py"):
        compile(path.read_text(), path.name, "exec")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Repository contract, privilege invariants and portable privacy checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(check())
