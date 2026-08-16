#!/usr/bin/env python3
"""Deployment Guard — data integrity plus deployed frontend verification."""

import os
from pathlib import Path
import subprocess
import sys

try:
    from .data_integrity_guard import capture_state, diff_states
except ImportError:
    from data_integrity_guard import capture_state, diff_states


SCRIPT_DIR = Path(__file__).resolve().parent
DATA_GUARD = SCRIPT_DIR / "data_integrity_guard.py"
VERIFY_COMMANDS = {"check", "verify"}


def _guard_environment() -> dict[str, str]:
    environment = os.environ.copy()
    env_path = SCRIPT_DIR.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            key, separator, value = line.partition("=")
            if separator and key.startswith("DEPLOY_GUARD_") and key not in environment:
                environment[key] = value.strip().strip('"').strip("'")
    return environment


def _run_frontend_checks() -> int:
    web_root = Path(os.environ.get("DREAMWEAVER_WEB_ROOT", "/opt/dreamweaver-web"))
    checks = (
        ("production artifact", web_root / "scripts" / "verify-production-artifact.mjs"),
        ("browser journeys", web_root / "scripts" / "verify-production-browser.mjs"),
    )
    environment = _guard_environment()
    for label, script in checks:
        if not script.exists():
            print(f"\n  ❌ Deployment Guard: {label} check is missing: {script}")
            return 1
        result = subprocess.run(["node", str(script)], cwd=web_root, env=environment)
        if result.returncode != 0:
            print(f"\n  ❌ Deployment Guard: {label} check failed")
            return result.returncode
    print("\n  ✅ Deployment Guard: artifact and browser journeys passed")
    return 0


def main() -> int:
    arguments = sys.argv[1:]
    integrity_result = subprocess.run([sys.executable, str(DATA_GUARD), *arguments])
    if integrity_result.returncode != 0:
        return integrity_result.returncode
    if arguments and arguments[0] in VERIFY_COMMANDS:
        return _run_frontend_checks()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
