from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
DEPLOY_DIR = ROOT_DIR / "deploy"
DEFAULT_ENV_FILE = DEPLOY_DIR / "server.env"
DEFAULT_VENV_DIR = ROOT_DIR / ".server-venv"
DEFAULT_APP_HOME = ROOT_DIR / ".server-data"


class CommandExecutionError(RuntimeError):
    def __init__(self, *, label: str, command: list[str], returncode: int, output: str) -> None:
        self.label = label
        self.command = command
        self.returncode = returncode
        self.output = output
        super().__init__(f"{label} failed with exit code {returncode}")


def is_windows() -> bool:
    return platform.system().lower() == "windows"


def print_info(message: str) -> None:
    _console_write(f"[INFO] {message}")


def print_ok(message: str) -> None:
    _console_write(f"[OK] {message}")


def print_warn(message: str) -> None:
    _console_write(f"[WARN] {message}")


def print_error(message: str) -> None:
    _console_write(f"[ERR] {message}")


def print_block(message: str = "") -> None:
    _console_write(message)


def _console_write(message: str) -> None:
    text = f"{message}\n"
    encoding = sys.stdout.encoding or "utf-8"
    data = text.encode(encoding, errors="replace")
    if getattr(sys.stdout, "buffer", None) is not None:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
        return
    sys.stdout.write(data.decode(encoding, errors="replace"))
    sys.stdout.flush()


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


def tail_text(text: str, *, lines: int = 20) -> str:
    if not text.strip():
        return ""
    buffer = deque((line.rstrip() for line in text.splitlines() if line.strip()), maxlen=max(lines, 1))
    return "\n".join(buffer)


def tail_file(path: Path, *, lines: int = 20) -> str:
    if not path.exists():
        return ""
    try:
        return tail_text(path.read_text(encoding="utf-8", errors="ignore"), lines=lines)
    except OSError:
        return ""


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    label: str | None = None,
    quiet: bool = True,
) -> str:
    result = subprocess.run(
        command,
        cwd=str(cwd or ROOT_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    output = result.stdout.decode("utf-8", errors="ignore")
    if result.returncode != 0:
        raise CommandExecutionError(
            label=label or command[0],
            command=command,
            returncode=result.returncode,
            output=output,
        )
    if not quiet and output.strip():
        print(output)
    return output


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


def _resolve_env_path(value: str) -> str:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = (ROOT_DIR / candidate).resolve()
    else:
        candidate = candidate.resolve()
    return str(candidate)


def normalize_runtime_path_env(env: dict[str, str]) -> dict[str, str]:
    normalized = dict(env)
    for key in (
        "MEETING_ASSISTANT_HOME",
        "MEETING_ASSISTANT_DATA_DIR",
        "MEETING_ASSISTANT_LOG_DIR",
        "MEETING_ASSISTANT_FRONTEND_DIST",
    ):
        raw = str(normalized.get(key, "")).strip()
        if raw:
            normalized[key] = _resolve_env_path(raw)
    return normalized


def merge_env(env_file: Path = DEFAULT_ENV_FILE) -> dict[str, str]:
    merged = os.environ.copy()
    merged.update(load_env_file(env_file))
    merged.setdefault("PYTHONUNBUFFERED", "1")
    return normalize_runtime_path_env(merged)


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
        "MEETING_ASSISTANT_NGINX_HOME": "",
        "MEETING_ASSISTANT_RESTART_DELAY": "5",
        "MEETING_ASSISTANT_LOG_LEVEL": "info",
        "MEETING_ASSISTANT_LOG_FORMAT": "json",
        "MEETING_ASSISTANT_RUNTIME_COORDINATION": "sqlite",
        "MEETING_ASSISTANT_WORKERS": "1",
        "MEETING_ASSISTANT_PROXY_HEADERS": "1",
        "MEETING_ASSISTANT_FORWARDED_ALLOW_IPS": "127.0.0.1",
        "MEETING_ASSISTANT_TIMEOUT_KEEP_ALIVE": "30",
        "MEETING_ASSISTANT_BACKLOG": "2048",
        "MEETING_ASSISTANT_LIMIT_CONCURRENCY": "0",
        "MEETING_ASSISTANT_LIMIT_MAX_REQUESTS": "0",
        "MEETING_ASSISTANT_ENABLE_ACCESS_LOG": "0",
    }
    env_file.write_text(
        "\n".join(
            [
                "# Server deployment config for Meeting Assistant",
                "# Edit this file before you deploy to a real server if needed.",
                *[f"{key}={value}" for key, value in defaults.items()],
                "",
            ]
        ),
        encoding="utf-8",
    )
    return env_file


def ensure_runtime_dirs(env_file: Path = DEFAULT_ENV_FILE) -> dict[str, Path]:
    env = normalize_runtime_path_env(load_env_file(env_file))
    app_home = Path(env.get("MEETING_ASSISTANT_HOME", str(DEFAULT_APP_HOME))).expanduser().resolve()
    log_dir = Path(env.get("MEETING_ASSISTANT_LOG_DIR", str(app_home / "logs"))).expanduser().resolve()
    control_dir = app_home / "control"
    app_home.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    control_dir.mkdir(parents=True, exist_ok=True)
    return {"app_home": app_home, "log_dir": log_dir, "control_dir": control_dir}


def ensure_venv(venv_dir: Path = DEFAULT_VENV_DIR) -> Path:
    python_executable = get_venv_python(venv_dir)
    if python_executable.exists():
        return python_executable

    run([sys.executable, "-m", "venv", str(venv_dir)], label="创建 Python 虚拟环境")
    return python_executable


def http_ok(url: str, *, timeout_sec: float = 2.0) -> tuple[bool, str]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            return 200 <= response.status < 400, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
