from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from common import (
    BACKEND_DIR,
    DEFAULT_ENV_FILE,
    DEFAULT_VENV_DIR,
    ROOT_DIR,
    ensure_env_file,
    ensure_runtime_dirs,
    ensure_venv,
    get_venv_python,
    merge_env,
)


SHUTTING_DOWN = False
CHILD_PROCESS: subprocess.Popen[str] | None = None


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _write_line(log_file: Path, message: str) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(f"[{_timestamp()}] {message}\n")


def _handle_stop(signum: int, _frame) -> None:
    global SHUTTING_DOWN
    SHUTTING_DOWN = True
    if CHILD_PROCESS and CHILD_PROCESS.poll() is None:
        try:
            CHILD_PROCESS.terminate()
        except Exception:  # noqa: BLE001
            pass


def _build_command(env: dict[str, str], env_file: Path) -> list[str]:
    venv_python = get_venv_python(DEFAULT_VENV_DIR)
    host = env.get("MEETING_ASSISTANT_HOST", "0.0.0.0")
    port = env.get("MEETING_ASSISTANT_PORT", "5173")
    log_level = env.get("MEETING_ASSISTANT_LOG_LEVEL", "info")

    command = [
        str(venv_python),
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        host,
        "--port",
        port,
        "--log-level",
        log_level,
    ]
    env["MEETING_ASSISTANT_SERVE_FRONTEND"] = env.get("MEETING_ASSISTANT_SERVE_FRONTEND", "1")
    env["MEETING_ASSISTANT_FRONTEND_DIST"] = env.get(
        "MEETING_ASSISTANT_FRONTEND_DIST",
        str((ROOT_DIR / "dist").resolve()),
    )
    env["MEETING_ASSISTANT_ENV_FILE"] = str(env_file)
    return command


def main() -> int:
    parser = argparse.ArgumentParser(description="Crash-resilient runner for Meeting Assistant")
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE),
        help="Path to the deployment env file",
    )
    args = parser.parse_args()

    env_file = Path(args.env_file).expanduser().resolve()
    ensure_env_file(env_file)
    ensure_venv(DEFAULT_VENV_DIR)
    paths = ensure_runtime_dirs(env_file)
    env = merge_env(env_file)

    restart_delay = max(1, int(env.get("MEETING_ASSISTANT_RESTART_DELAY", "5")))
    log_dir = Path(env.get("MEETING_ASSISTANT_LOG_DIR", str(paths["log_dir"]))).expanduser().resolve()
    runner_log = log_dir / "runner.log"
    app_log = log_dir / "app.log"

    signal.signal(signal.SIGINT, _handle_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_stop)

    command = _build_command(env, env_file)
    _write_line(runner_log, f"runner started, env={env_file}")

    while not SHUTTING_DOWN:
        _write_line(runner_log, f"starting child: {' '.join(command)}")
        with app_log.open("a", encoding="utf-8") as output:
            global CHILD_PROCESS
            CHILD_PROCESS = subprocess.Popen(
                command,
                cwd=str(BACKEND_DIR),
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
                text=True,
            )
            exit_code = CHILD_PROCESS.wait()

        if SHUTTING_DOWN:
            break

        _write_line(runner_log, f"child exited with code {exit_code}, restarting in {restart_delay}s")
        time.sleep(restart_delay)

    _write_line(runner_log, "runner stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
