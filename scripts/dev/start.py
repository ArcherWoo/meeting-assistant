#!/usr/bin/env python3
"""
Development launcher for Meeting Assistant.

Default behavior:
- auto-check Python / Node
- auto-install missing dependencies
- auto-stop stale dev processes
- start backend + frontend quietly
- wait until both sides are healthy
- only show detailed logs when startup fails or when --verbose is used
"""

from __future__ import annotations

import argparse
import json
import locale
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


IS_WINDOWS = platform.system() == "Windows"
ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
REQUIREMENTS_FILE = BACKEND_DIR / "requirements.txt"
NODE_MODULES_DIR = ROOT_DIR / "node_modules"
RUNTIME_DIR = ROOT_DIR / ".dev-runtime"
LOG_DIR = RUNTIME_DIR / "logs"
STATE_FILE = RUNTIME_DIR / "launcher-processes.json"
DEFAULT_BACKEND_PORT = 5173
DEFAULT_FRONTEND_PORT = 4173
PROCESSES: list[dict] = []
SHUTDOWN_REQUESTED = threading.Event()
FORCE_SHUTDOWN = threading.Event()
SHUTDOWN_LOCK = threading.Lock()
SHUTDOWN_DONE = False
ARGS: argparse.Namespace

RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
OUTPUT_ENCODINGS = tuple(
    dict.fromkeys(
        encoding
        for encoding in (
            "utf-8",
            locale.getpreferredencoding(False),
            "gbk",
            "mbcs" if IS_WINDOWS else None,
        )
        if encoding
    )
)


def _enable_windows_ansi() -> None:
    if not IS_WINDOWS:
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def info(message: str) -> None:
    print(f"[INFO] {message}")


def ok(message: str) -> None:
    print(f"[OK] {message}")


def warn(message: str) -> None:
    print(f"[WARN] {message}")


def fail(message: str) -> None:
    print(f"[ERR] {message}")
    raise SystemExit(1)


def _decode_output_chunk(chunk: bytes) -> str:
    for encoding in OUTPUT_ENCODINGS:
        try:
            return chunk.decode(encoding)
        except UnicodeDecodeError:
            continue
    return chunk.decode("utf-8", errors="replace")


def _tail_file(path: Path, *, lines: int = 25) -> str:
    if not path.exists():
        return ""
    try:
        content = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ""
    return "\n".join(content[-lines:])


def _show_log_tail(title: str, path: Path) -> None:
    tail = _tail_file(path)
    if not tail:
        return
    print("")
    print(f"{BOLD}{title}{RESET}")
    print(tail)


def _npm_command() -> str:
    return "npm.cmd" if IS_WINDOWS else "npm"


def _http_ok(url: str, *, timeout_sec: float = 2.0) -> bool:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            return 200 <= response.status < 400
    except urllib.error.HTTPError as exc:
        return 200 <= exc.code < 400
    except Exception:
        return False


def _network_ipv4_addresses() -> list[str]:
    addresses: list[str] = []

    def add(ip: str) -> None:
        normalized = str(ip or "").strip()
        if not normalized or normalized.startswith("127."):
            return
        if normalized in addresses:
            return
        addresses.append(normalized)

    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(item[4][0])
    except Exception:
        pass

    for target in ("8.8.8.8", "1.1.1.1"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((target, 80))
                add(sock.getsockname()[0])
        except Exception:
            continue

    private_first = sorted(
        addresses,
        key=lambda ip: (
            0 if ip.startswith("192.168.") else 1 if ip.startswith("172.") else 2 if ip.startswith("10.") else 3,
            ip,
        ),
    )
    return private_first


def _wait_http(url: str, *, timeout_sec: float) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if _http_ok(url):
            return True
        if SHUTDOWN_REQUESTED.is_set():
            return False
        time.sleep(0.5)
    return False


def _required_python_packages() -> list[str]:
    if not REQUIREMENTS_FILE.exists():
        return []
    packages: list[str] = []
    for raw_line in REQUIREMENTS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        package = line.split("==")[0].split(">=")[0].split("<=")[0].split("[")[0].strip()
        if package:
            packages.append(package)
    return packages


def _python_import_name(package_name: str) -> str:
    overrides = {
        "python-pptx": "pptx",
        "python-multipart": "multipart",
        "pydantic-ai-slim": "pydantic_ai",
        "python-jose": "jose",
        "Pillow": "PIL",
        "PyMuPDF": "fitz",
    }
    return overrides.get(package_name, package_name.replace("-", "_").lower())


def _run_command(command: list[str], *, cwd: Path, label: str) -> str:
    result = subprocess.run(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    output = _decode_output_chunk(result.stdout or b"")
    if result.returncode != 0:
        print("")
        print(f"{BOLD}{label}失败{RESET}")
        tail = "\n".join([line for line in output.splitlines() if line.strip()][-25:])
        if tail:
            print(tail)
        raise SystemExit(result.returncode or 1)
    return output


def _summarize_pip_output(output: str) -> list[str]:
    summary: list[str] = []
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if any("Defaulting to user installation because normal site-packages is not writeable" in line for line in lines):
        summary.append("当前环境不可写，pip 已自动回退到用户目录安装。")
    installed_line = next((line for line in reversed(lines) if line.startswith("Successfully installed ")), None)
    if installed_line:
        packages = installed_line.removeprefix("Successfully installed ").strip()
        if packages:
            summary.append(f"已安装: {packages}")
    return summary


def _port_in_use(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _load_state() -> dict | None:
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def _pid_exists(pid: int) -> bool:
    if IS_WINDOWS:
        result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _cleanup_stale_state() -> None:
    state = _load_state()
    if not state:
        return
    processes = state.get("processes", [])
    alive = [entry for entry in processes if _pid_exists(int(entry.get("pid", 0) or 0))]
    if not alive:
        try:
            STATE_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        return

    warn("检测到旧的开发进程仍在运行，先自动停止它们。")
    subprocess.run([sys.executable, str(ROOT_DIR / "scripts" / "dev" / "stop.py")], cwd=str(ROOT_DIR), check=False)
    time.sleep(1.0)


def _write_runtime_state() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "root_dir": str(ROOT_DIR),
        "written_at": time.time(),
        "processes": [
            {
                "name": entry["name"],
                "pid": entry["process"].pid,
                "log_file": str(entry["log_file"]),
            }
            for entry in PROCESSES
            if entry["process"].poll() is None
        ],
    }
    STATE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _clear_runtime_state() -> None:
    try:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
        if RUNTIME_DIR.exists() and not any(RUNTIME_DIR.iterdir()):
            RUNTIME_DIR.rmdir()
    except Exception:
        pass


def check_python() -> None:
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 9):
        fail(f"需要 Python 3.9+，当前版本是 {major}.{minor}")
    ok(f"Python {major}.{minor} ({sys.executable})")


def check_node() -> None:
    node_path = shutil.which("node")
    npm_path = shutil.which(_npm_command()) or shutil.which("npm")
    if not node_path or not npm_path:
        fail("未检测到 Node.js 和 npm。请先安装 Node.js。")
    version = subprocess.check_output(["node", "--version"], text=True).strip()
    ok(f"Node.js {version}")


def ensure_python_dependencies() -> None:
    if ARGS.skip_install:
        warn("已跳过 Python 依赖检查")
        return

    missing: list[str] = []
    for package in _required_python_packages():
        try:
            __import__(_python_import_name(package))
        except ImportError:
            missing.append(package)

    if not missing:
        ok("Python 依赖已就绪")
        return

    warn(f"发现缺失的 Python 依赖：{', '.join(missing)}")
    output = _run_command(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--progress-bar",
            "off",
            "-r",
            str(REQUIREMENTS_FILE),
        ],
        cwd=ROOT_DIR,
        label="安装 Python 依赖",
    )
    for line in _summarize_pip_output(output):
        info(line)
    ok("Python 依赖安装完成")


def ensure_node_dependencies() -> None:
    if ARGS.skip_install:
        warn("已跳过前端依赖检查")
        return

    if NODE_MODULES_DIR.is_dir():
        ok("前端依赖已就绪")
        return

    warn("node_modules 不存在，开始自动安装前端依赖")
    _run_command([_npm_command(), "install", "--no-fund", "--no-audit", "--loglevel=error"], cwd=ROOT_DIR, label="安装前端依赖")
    ok("前端依赖安装完成")


def _launch_process(name: str, command: list[str], *, cwd: Path, env: dict[str, str], log_file: Path) -> subprocess.Popen:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    if ARGS.verbose:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            env=env,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0,
        )
        threading.Thread(target=_stream_output, args=(process, log_file, name), daemon=True).start()
    else:
        handle = log_file.open("a", encoding="utf-8")
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0,
        )
        process._meeting_assistant_log_handle = handle  # type: ignore[attr-defined]

    PROCESSES.append({"name": name, "process": process, "log_file": log_file})
    _write_runtime_state()
    return process


def _stream_output(process: subprocess.Popen, log_file: Path, name: str) -> None:
    if process.stdout is None:
        return
    with log_file.open("a", encoding="utf-8") as handle:
        while True:
            chunk = process.stdout.readline()
            if not chunk:
                break
            text = _decode_output_chunk(chunk)
            handle.write(text)
            handle.flush()
            print(f"[{name}] {text}", end="", flush=True)


def launch_backend() -> subprocess.Popen:
    return _launch_backend(reload=True)


def _launch_backend(*, reload: bool) -> subprocess.Popen:
    backend_log = LOG_DIR / "backend.log"
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    command = [
        sys.executable,
        "main.py",
        "--host",
        "127.0.0.1",
        "--port",
        str(ARGS.backend_port),
    ]
    if reload:
        command.append("--reload")
    return _launch_process(
        "backend",
        command,
        cwd=BACKEND_DIR,
        env=env,
        log_file=backend_log,
    )


def launch_frontend() -> subprocess.Popen:
    frontend_log = LOG_DIR / "frontend.log"
    env = {**os.environ, "VITE_DEV_API_TARGET": f"http://127.0.0.1:{ARGS.backend_port}"}
    return _launch_process(
        "frontend",
        [_npm_command(), "run", "dev"],
        cwd=ROOT_DIR,
        env=env,
        log_file=frontend_log,
    )


def _request_shutdown(reason: str) -> None:
    if SHUTDOWN_REQUESTED.is_set():
        FORCE_SHUTDOWN.set()
        return
    SHUTDOWN_REQUESTED.set()
    warn(f"收到停止请求：{reason}")


def _handle_signal(signum: int, _frame: object | None) -> None:
    try:
        name = signal.Signals(signum).name
    except Exception:
        name = str(signum)
    _request_shutdown(name)


def _send_graceful_stop(name: str, process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if IS_WINDOWS:
        ctrl_break = getattr(signal, "CTRL_BREAK_EVENT", None)
        if ctrl_break is not None:
            try:
                process.send_signal(ctrl_break)
                return
            except Exception:
                pass
        return
    try:
        process.terminate()
    except Exception:
        pass


def _force_stop(name: str, process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
        return
    try:
        process.kill()
    except Exception:
        pass


def shutdown() -> None:
    global SHUTDOWN_DONE
    with SHUTDOWN_LOCK:
        if SHUTDOWN_DONE:
            return
        SHUTDOWN_DONE = True

    for entry in PROCESSES:
        _send_graceful_stop(entry["name"], entry["process"])

    deadline = time.time() + 8.0
    while time.time() < deadline and not FORCE_SHUTDOWN.is_set():
        if all(entry["process"].poll() is not None for entry in PROCESSES):
            break
        time.sleep(0.2)

    for entry in PROCESSES:
        _force_stop(entry["name"], entry["process"])
        handle = getattr(entry["process"], "_meeting_assistant_log_handle", None)
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass

    _clear_runtime_state()
    ok("开发环境已停止")


def _watch_stdin_for_stop() -> None:
    if not sys.stdin or not sys.stdin.isatty():
        return
    while not SHUTDOWN_REQUESTED.is_set():
        try:
            line = sys.stdin.readline()
        except Exception:
            return
        if line == "":
            return
        if line.strip().lower() in {"q", "quit", "exit", "stop"}:
            _request_shutdown("stdin")
            return


def _check_child_processes() -> None:
    for entry in PROCESSES:
        exit_code = entry["process"].poll()
        if exit_code is None:
            continue
        if SHUTDOWN_REQUESTED.is_set():
            return
        warn(f"{entry['name']} 异常退出，退出码 {exit_code}")
        _show_log_tail(f"{entry['name']} 最近日志", entry["log_file"])
        _request_shutdown(f"{entry['name']} exited")
        return


def _find_process(name: str) -> dict | None:
    return next((entry for entry in PROCESSES if entry["name"] == name), None)


def _remove_process(name: str) -> None:
    global PROCESSES
    PROCESSES = [entry for entry in PROCESSES if entry["name"] != name]
    _write_runtime_state()


def _backend_reload_permission_issue() -> bool:
    tail = _tail_file(LOG_DIR / "backend.log", lines=400)
    return "CreateNamedPipe" in tail and "PermissionError: [WinError 5]" in tail


def _frontend_spawn_eperm_issue() -> bool:
    tail = _tail_file(LOG_DIR / "frontend.log", lines=200)
    return "Error: spawn EPERM" in tail


def _restart_backend_without_reload() -> bool:
    backend = _find_process("backend")
    if not backend or backend["process"].poll() is None:
        return False
    warn("检测到后端热重载权限异常，自动切换为无 reload 模式重试一次。")
    _remove_process("backend")
    _launch_backend(reload=False)
    return True


def _preflight_ports() -> None:
    for port, label in (
        (ARGS.backend_port, "后端"),
        (ARGS.frontend_port, "前端"),
    ):
        if _port_in_use(port):
            fail(f"{label}端口 {port} 已被占用。请先释放端口，或停止旧的开发进程。")


def _wait_services_ready() -> None:
    backend_url = f"http://127.0.0.1:{ARGS.backend_port}/api/health/live"
    frontend_url = f"http://127.0.0.1:{ARGS.frontend_port}"
    backend_deadline = time.time() + ARGS.startup_timeout
    frontend_deadline = time.time() + ARGS.startup_timeout
    backend_retry_without_reload = True

    while time.time() < backend_deadline:
        if _http_ok(backend_url):
            break
        backend = _find_process("backend")
        if backend and backend["process"].poll() is not None:
            if backend_retry_without_reload and _backend_reload_permission_issue():
                backend_retry_without_reload = False
                _restart_backend_without_reload()
                backend_deadline = time.time() + ARGS.startup_timeout
                continue
            _show_log_tail("后端启动失败日志", LOG_DIR / "backend.log")
            fail("后端启动失败。")
        frontend = _find_process("frontend")
        if frontend and frontend["process"].poll() is not None:
            _show_log_tail("前端启动失败日志", LOG_DIR / "frontend.log")
            fail("前端启动失败。")
        time.sleep(0.5)
    else:
        _show_log_tail("后端启动失败日志", LOG_DIR / "backend.log")
        fail(f"后端没有在 {ARGS.startup_timeout:.0f} 秒内启动成功。")

    while time.time() < frontend_deadline:
        if _http_ok(frontend_url):
            return
        frontend = _find_process("frontend")
        if frontend and frontend["process"].poll() is not None:
            _show_log_tail("前端启动失败日志", LOG_DIR / "frontend.log")
            if _frontend_spawn_eperm_issue():
                fail("前端启动失败：当前环境禁止 esbuild 派生子进程（spawn EPERM）。请在本机正常终端运行，或检查安全软件/系统策略。")
            fail("前端启动失败。")
        time.sleep(0.5)

    _show_log_tail("前端启动失败日志", LOG_DIR / "frontend.log")
    fail(f"前端没有在 {ARGS.startup_timeout:.0f} 秒内启动成功。")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Meeting Assistant 开发环境一键启动")
    parser.add_argument("--verbose", action="store_true", help="启动后持续输出后端和前端日志")
    parser.add_argument("--skip-install", action="store_true", help="跳过自动安装依赖")
    parser.add_argument("--backend-port", type=int, default=DEFAULT_BACKEND_PORT)
    parser.add_argument("--frontend-port", type=int, default=DEFAULT_FRONTEND_PORT)
    parser.add_argument("--startup-timeout", type=float, default=45.0, help="等待服务启动成功的秒数")
    return parser.parse_args()


def main() -> None:
    global ARGS
    ARGS = parse_args()
    _enable_windows_ansi()

    print("")
    print(f"{BOLD}{CYAN}Meeting Assistant 开发环境启动器{RESET}")
    print("")

    check_python()
    check_node()
    ensure_python_dependencies()
    ensure_node_dependencies()
    _cleanup_stale_state()
    _preflight_ports()

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)

    try:
        launch_backend()
        launch_frontend()
        threading.Thread(target=_watch_stdin_for_stop, daemon=True).start()
        _wait_services_ready()

        print("")
        ok("开发环境启动成功")
        print("智枢前端:")
        print(f"  Local:    http://localhost:{ARGS.frontend_port}")
        for ip in _network_ipv4_addresses():
            print(f"  Network:  http://{ip}:{ARGS.frontend_port}")
        print("后端接口:")
        print(f"  Local:    http://127.0.0.1:{ARGS.backend_port}")
        for ip in _network_ipv4_addresses():
            print(f"  Network:  http://{ip}:{ARGS.backend_port}")
        print(f"日志目录:   {LOG_DIR}")
        print("停止方式:   Ctrl+C，或另开终端运行 python scripts/dev/stop.py")
        if not ARGS.verbose:
            print("日志策略:   当前为安静模式；如需实时日志，请改用 python start.py --verbose")
        print("")

        while not SHUTDOWN_REQUESTED.is_set():
            _check_child_processes()
            time.sleep(0.25)
    finally:
        if PROCESSES:
            shutdown()


if __name__ == "__main__":
    main()
