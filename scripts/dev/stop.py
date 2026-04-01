#!/usr/bin/env python3
"""
Stop the Meeting Assistant development services started by scripts/dev/start.py.
"""

from __future__ import annotations

import json
import os
import platform
import signal
import subprocess
import time
from pathlib import Path


IS_WINDOWS = platform.system() == "Windows"
ROOT_DIR = Path(__file__).resolve().parents[2]
RUNTIME_DIR = ROOT_DIR / ".dev-runtime"
STATE_FILE = RUNTIME_DIR / "launcher-processes.json"


def info(message: str) -> None:
    print(f"[stop] {message}")


def warn(message: str) -> None:
    print(f"[stop] WARN: {message}")


def _load_state() -> dict | None:
    if not STATE_FILE.exists():
        warn(f"No runtime state file found at {STATE_FILE}.")
        return None

    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warn(f"Could not read runtime state: {exc}")
        return None


def _pid_exists(pid: int) -> bool:
    if IS_WINDOWS:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
        )
        return str(pid) in result.stdout

    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _graceful_stop(name: str, pid: int) -> None:
    if not _pid_exists(pid):
        return

    if IS_WINDOWS:
        subprocess.run(["taskkill", "/T", "/PID", str(pid)], capture_output=True)
        info(f"Sent stop request to {name} (PID {pid})")
        return

    try:
        os.kill(pid, signal.SIGTERM)
        info(f"Sent SIGTERM to {name} (PID {pid})")
    except OSError as exc:
        warn(f"Could not stop {name} (PID {pid}): {exc}")


def _force_stop(name: str, pid: int) -> None:
    if not _pid_exists(pid):
        return

    if IS_WINDOWS:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        warn(f"Force-killed {name} (PID {pid})")
        return

    try:
        os.kill(pid, signal.SIGKILL)
        warn(f"Force-killed {name} (PID {pid})")
    except OSError as exc:
        warn(f"Could not force-kill {name} (PID {pid}): {exc}")


def _cleanup_state() -> None:
    try:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
        if RUNTIME_DIR.exists() and not any(RUNTIME_DIR.iterdir()):
            RUNTIME_DIR.rmdir()
    except OSError:
        pass


def main() -> None:
    state = _load_state()
    if not state:
        raise SystemExit(1)

    processes = state.get("processes", [])
    if not processes:
        warn("Runtime state did not contain any tracked processes.")
        _cleanup_state()
        raise SystemExit(1)

    for entry in processes:
        _graceful_stop(entry.get("name", "process"), int(entry["pid"]))

    deadline = time.time() + 8.0
    while time.time() < deadline:
        alive = [entry for entry in processes if _pid_exists(int(entry["pid"]))]
        if not alive:
            break
        time.sleep(0.2)

    for entry in processes:
        _force_stop(entry.get("name", "process"), int(entry["pid"]))

    _cleanup_state()
    info("Shutdown complete.")


if __name__ == "__main__":
    main()
