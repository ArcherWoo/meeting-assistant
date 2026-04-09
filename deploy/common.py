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
REQUIREMENTS_FILE = BACKEND_DIR / "requirements.txt"

PYTHON_IMPORT_OVERRIDES = {
    "python-pptx": "pptx",
    "python-multipart": "multipart",
    "pydantic-ai-slim": "pydantic_ai",
    "python-jose": "jose",
    "Pillow": "PIL",
    "PyMuPDF": "fitz",
}

AUTO_PIP_ENV_KEYS = (
    "MEETING_ASSISTANT_VENV_SYSTEM_SITE_PACKAGES",
    "MEETING_ASSISTANT_PIP_INDEX_URL",
    "MEETING_ASSISTANT_PIP_EXTRA_INDEX_URL",
    "MEETING_ASSISTANT_PIP_TRUSTED_HOST",
    "MEETING_ASSISTANT_PIP_FIND_LINKS",
    "MEETING_ASSISTANT_PIP_NO_INDEX",
    "MEETING_ASSISTANT_PIP_ARGS",
)


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


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    return normalized in {"1", "true", "yes", "on"}


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


def _strip_pip_config_value(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def detect_pip_settings(python_executable: Path | str | None = None) -> dict[str, str]:
    detected: dict[str, str] = {}
    env_mapping = {
        "PIP_INDEX_URL": "MEETING_ASSISTANT_PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL": "MEETING_ASSISTANT_PIP_EXTRA_INDEX_URL",
        "PIP_TRUSTED_HOST": "MEETING_ASSISTANT_PIP_TRUSTED_HOST",
        "PIP_FIND_LINKS": "MEETING_ASSISTANT_PIP_FIND_LINKS",
        "PIP_NO_INDEX": "MEETING_ASSISTANT_PIP_NO_INDEX",
    }
    for pip_env_key, deploy_key in env_mapping.items():
        raw = os.environ.get(pip_env_key, "").strip()
        if raw:
            detected[deploy_key] = raw

    pip_config: dict[str, str] = {}
    python_cmd = str(python_executable or sys.executable)
    try:
        output = run([python_cmd, "-m", "pip", "config", "list"], label="读取 pip 配置")
    except Exception:  # noqa: BLE001
        output = ""
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        pip_config[key.strip().lower()] = _strip_pip_config_value(value)

    pip_config_mapping = {
        "MEETING_ASSISTANT_PIP_INDEX_URL": ("global.index-url", "install.index-url"),
        "MEETING_ASSISTANT_PIP_EXTRA_INDEX_URL": ("global.extra-index-url", "install.extra-index-url"),
        "MEETING_ASSISTANT_PIP_TRUSTED_HOST": ("global.trusted-host", "install.trusted-host"),
        "MEETING_ASSISTANT_PIP_FIND_LINKS": ("global.find-links", "install.find-links"),
        "MEETING_ASSISTANT_PIP_NO_INDEX": ("global.no-index", "install.no-index"),
    }
    for deploy_key, pip_keys in pip_config_mapping.items():
        if detected.get(deploy_key):
            continue
        for pip_key in pip_keys:
            value = pip_config.get(pip_key, "").strip()
            if value:
                detected[deploy_key] = value
                break

    return detected


def build_server_env_defaults(python_executable: Path | str | None = None) -> dict[str, str]:
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
        "MEETING_ASSISTANT_VENV_SYSTEM_SITE_PACKAGES": "1",
        "MEETING_ASSISTANT_PIP_INDEX_URL": "",
        "MEETING_ASSISTANT_PIP_EXTRA_INDEX_URL": "",
        "MEETING_ASSISTANT_PIP_TRUSTED_HOST": "",
        "MEETING_ASSISTANT_PIP_FIND_LINKS": "",
        "MEETING_ASSISTANT_PIP_NO_INDEX": "",
        "MEETING_ASSISTANT_PIP_ARGS": "",
    }
    defaults.update(detect_pip_settings(python_executable))
    return defaults


def ensure_env_file(env_file: Path = DEFAULT_ENV_FILE) -> Path:
    DEPLOY_DIR.mkdir(parents=True, exist_ok=True)

    if env_file.exists():
        return env_file

    defaults = build_server_env_defaults()
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


def backfill_env_file(env_file: Path = DEFAULT_ENV_FILE, *, python_executable: Path | str | None = None) -> Path:
    ensure_env_file(env_file)
    detected_defaults = build_server_env_defaults(python_executable)
    lines = env_file.read_text(encoding="utf-8").splitlines()
    current_values = load_env_file(env_file)
    key_to_index: dict[str, int] = {}
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _value = line.split("=", 1)
        key_to_index[key.strip()] = index

    changed = False
    for key in AUTO_PIP_ENV_KEYS:
        detected_value = str(detected_defaults.get(key, "")).strip()
        current_value = str(current_values.get(key, "")).strip()
        if current_value or not detected_value:
            continue
        replacement = f"{key}={detected_value}"
        if key in key_to_index:
            lines[key_to_index[key]] = replacement
        else:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append("# Auto-detected package source settings")
            lines.append(replacement)
        current_values[key] = detected_value
        changed = True

    if changed:
        env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
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


def _venv_uses_system_site_packages(venv_dir: Path) -> bool:
    config_file = venv_dir / "pyvenv.cfg"
    if not config_file.exists():
        return False
    try:
        for raw_line in config_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line.lower().startswith("include-system-site-packages"):
                continue
            _, _, value = line.partition("=")
            return value.strip().lower() == "true"
    except OSError:
        return False
    return False


def ensure_venv(venv_dir: Path = DEFAULT_VENV_DIR) -> Path:
    python_executable = get_venv_python(venv_dir)
    wants_system_site_packages = _truthy(
        os.environ.get("MEETING_ASSISTANT_VENV_SYSTEM_SITE_PACKAGES"),
        default=True,
    )
    if python_executable.exists():
        if wants_system_site_packages and not _venv_uses_system_site_packages(venv_dir):
            shutil.rmtree(venv_dir, ignore_errors=True)
        else:
            return python_executable

    if venv_dir.exists() and not python_executable.exists():
        shutil.rmtree(venv_dir, ignore_errors=True)

    if python_executable.exists():
        return python_executable

    command = [sys.executable, "-m", "venv"]
    if wants_system_site_packages:
        command.append("--system-site-packages")
    command.append(str(venv_dir))
    run(command, label="创建 Python 虚拟环境")
    return python_executable


def _parse_requirement_package(raw_line: str) -> str:
    token = raw_line.strip()
    for marker in ("==", ">=", "<=", "~=", "!=", "<", ">"):
        if marker in token:
            token = token.split(marker, 1)[0].strip()
            break
    return token


def _python_import_name(requirement_line: str) -> str:
    package = _parse_requirement_package(requirement_line)
    base = package.split("[", 1)[0].strip()
    return PYTHON_IMPORT_OVERRIDES.get(base, base.replace("-", "_").lower())


def parse_requirements(requirements_file: Path = REQUIREMENTS_FILE) -> list[str]:
    if not requirements_file.exists():
        return []
    requirements: list[str] = []
    for raw_line in requirements_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        requirements.append(line)
    return requirements


def python_can_import(python_executable: Path | str, import_name: str) -> bool:
    result = subprocess.run(
        [
            str(python_executable),
            "-c",
            "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec(sys.argv[1]) else 1)",
            import_name,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return result.returncode == 0


def detect_missing_requirements(
    python_executable: Path | str,
    requirements_file: Path = REQUIREMENTS_FILE,
) -> list[str]:
    missing: list[str] = []
    for requirement in parse_requirements(requirements_file):
        if not python_can_import(python_executable, _python_import_name(requirement)):
            missing.append(requirement)
    return missing


def build_pip_env(env_file: Path = DEFAULT_ENV_FILE) -> dict[str, str]:
    env = merge_env(env_file)
    mirror_index = env.get("MEETING_ASSISTANT_PIP_INDEX_URL", "").strip()
    extra_index = env.get("MEETING_ASSISTANT_PIP_EXTRA_INDEX_URL", "").strip()
    trusted_host = env.get("MEETING_ASSISTANT_PIP_TRUSTED_HOST", "").strip()
    find_links = env.get("MEETING_ASSISTANT_PIP_FIND_LINKS", "").strip()
    no_index = env.get("MEETING_ASSISTANT_PIP_NO_INDEX", "").strip()

    if mirror_index:
        env["PIP_INDEX_URL"] = mirror_index
    if extra_index:
        env["PIP_EXTRA_INDEX_URL"] = extra_index
    if trusted_host:
        env["PIP_TRUSTED_HOST"] = trusted_host
    if find_links:
        env["PIP_FIND_LINKS"] = find_links
    if no_index:
        env["PIP_NO_INDEX"] = no_index
    return env


def _split_extra_pip_args(raw_value: str) -> list[str]:
    if not raw_value.strip():
        return []
    return [item for item in raw_value.split() if item]


def _relax_requirement(requirement: str) -> str:
    package = _parse_requirement_package(requirement)
    return package if package else requirement


def install_requirement(
    python_executable: Path | str,
    requirement: str,
    *,
    env_file: Path = DEFAULT_ENV_FILE,
) -> tuple[bool, str, str]:
    pip_env = build_pip_env(env_file)
    extra_args = _split_extra_pip_args(pip_env.get("MEETING_ASSISTANT_PIP_ARGS", ""))
    base_command = [
        str(python_executable),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--progress-bar",
        "off",
        *extra_args,
    ]
    try:
        output = run(base_command + [requirement], env=pip_env, label=f"install {requirement}")
        return True, requirement, output
    except CommandExecutionError as exc:
        relaxed = _relax_requirement(requirement)
        if relaxed != requirement:
            try:
                output = run(base_command + [relaxed], env=pip_env, label=f"install {relaxed}")
                return True, relaxed, output
            except CommandExecutionError as relaxed_exc:
                combined = (
                    f"精确版本安装失败: {requirement}\n"
                    f"{tail_text(exc.output, lines=12)}\n\n"
                    f"回退版本安装失败: {relaxed}\n"
                    f"{tail_text(relaxed_exc.output, lines=12)}"
                )
                return False, relaxed, combined
        return False, requirement, tail_text(exc.output, lines=20)


def ensure_python_runtime_ready(
    python_executable: Path | str,
    *,
    env_file: Path = DEFAULT_ENV_FILE,
    requirements_file: Path = REQUIREMENTS_FILE,
) -> list[str]:
    missing = detect_missing_requirements(python_executable, requirements_file)
    if not missing:
        return ["复用当前可用 Python 环境，未发现缺失后端依赖。"]

    summaries = [f"检测到缺失依赖 {len(missing)} 个，开始仅安装缺失项。"]
    failures: list[str] = []
    for requirement in missing:
        ok, installed_as, output = install_requirement(
            python_executable,
            requirement,
            env_file=env_file,
        )
        if ok:
            if installed_as == requirement:
                summaries.append(f"已安装 {requirement}")
            else:
                summaries.append(f"{requirement} 在镜像源不可用，已自动回退安装 {installed_as}")
            continue
        failures.append(f"{requirement}\n{output}")

    still_missing = detect_missing_requirements(python_executable, requirements_file)
    if still_missing:
        detail = "\n\n".join(failures) if failures else "仍有依赖未满足。"
        raise RuntimeError(
            "后端依赖准备失败。\n"
            f"缺失依赖: {', '.join(still_missing)}\n"
            f"{detail}\n"
            "请在 deploy/server.env 中配置公司的 pip 镜像参数，"
            "或先使用能成功运行 start.py 的同一 Python 环境预装这些依赖。"
        )
    return summaries


def http_ok(url: str, *, timeout_sec: float = 2.0) -> tuple[bool, str]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            return 200 <= response.status < 400, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
