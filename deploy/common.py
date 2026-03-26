from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
DEPLOY_DIR = ROOT_DIR / "deploy"
DEFAULT_ENV_FILE = DEPLOY_DIR / "server.env"
DEFAULT_VENV_DIR = ROOT_DIR / ".server-venv"
DEFAULT_APP_HOME = ROOT_DIR / ".server-data"


def is_windows() -> bool:
    return platform.system().lower() == "windows"


def default_python_for_shell() -> str:
    if is_windows():
        if shutil.which("py"):
            return "py -3"
        return "python"
    return shutil.which("python3") or shutil.which("python") or "python3"


def get_venv_python(venv_dir: Path = DEFAULT_VENV_DIR) -> Path:
    if is_windows():
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=str(cwd or ROOT_DIR), env=env, check=True)


def load_env_file(env_file: Path = DEFAULT_ENV_FILE) -> dict[str, str]:
    if not env_file.exists():
        return {}

    loaded: dict[str, str] = {}
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        loaded[key.strip()] = value.strip()
    return loaded


def merge_env(env_file: Path = DEFAULT_ENV_FILE) -> dict[str, str]:
    merged = os.environ.copy()
    merged.update(load_env_file(env_file))
    merged.setdefault("PYTHONUNBUFFERED", "1")
    return merged


def ensure_env_file(env_file: Path = DEFAULT_ENV_FILE) -> Path:
    DEPLOY_DIR.mkdir(parents=True, exist_ok=True)

    if env_file.exists():
        return env_file

    defaults = {
        "MEETING_ASSISTANT_HOST": "0.0.0.0",
        "MEETING_ASSISTANT_PORT": "5173",
        "MEETING_ASSISTANT_SERVE_FRONTEND": "1",
        "MEETING_ASSISTANT_FRONTEND_DIST": str((ROOT_DIR / "dist").resolve()),
        "MEETING_ASSISTANT_HOME": str(DEFAULT_APP_HOME.resolve()),
        "MEETING_ASSISTANT_LOG_DIR": str((DEFAULT_APP_HOME / "logs").resolve()),
        "MEETING_ASSISTANT_RESTART_DELAY": "5",
        "MEETING_ASSISTANT_LOG_LEVEL": "info",
    }
    env_file.write_text(
        "\n".join([
            "# Server deployment config for Meeting Assistant",
            "# Adjust host/port/path values here when you deploy to a real server.",
            *[f"{key}={value}" for key, value in defaults.items()],
            "",
        ]),
        encoding="utf-8",
    )
    return env_file


def ensure_runtime_dirs(env_file: Path = DEFAULT_ENV_FILE) -> dict[str, Path]:
    env = load_env_file(env_file)
    app_home = Path(env.get("MEETING_ASSISTANT_HOME", str(DEFAULT_APP_HOME))).expanduser().resolve()
    log_dir = Path(env.get("MEETING_ASSISTANT_LOG_DIR", str(app_home / "logs"))).expanduser().resolve()
    app_home.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    return {"app_home": app_home, "log_dir": log_dir}


def ensure_venv(venv_dir: Path = DEFAULT_VENV_DIR) -> Path:
    python_executable = get_venv_python(venv_dir)
    if python_executable.exists():
        return python_executable

    run([sys.executable, "-m", "venv", str(venv_dir)])
    return python_executable
