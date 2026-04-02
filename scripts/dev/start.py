#!/usr/bin/env python3
"""
Development launcher for Meeting Assistant.

It validates the local environment, installs missing dependencies when needed,
then starts the backend and frontend dev servers together.
"""

from __future__ import annotations

import json
import locale
import os
import platform
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


IS_WINDOWS = platform.system() == "Windows"
ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
REQUIREMENTS_FILE = BACKEND_DIR / "requirements.txt"
NODE_MODULES_DIR = ROOT_DIR / "node_modules"
RUNTIME_DIR = ROOT_DIR / ".dev-runtime"
STATE_FILE = RUNTIME_DIR / "launcher-processes.json"
PROCESSES: list[tuple[str, subprocess.Popen]] = []
SHUTDOWN_REQUESTED = threading.Event()
FORCE_SHUTDOWN = threading.Event()
SHUTDOWN_LOCK = threading.Lock()
SHUTDOWN_DONE = False

RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
BLUE = "\033[34m"
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
    print(f"  {CYAN}[INFO] {message}{RESET}")


def ok(message: str) -> None:
    print(f"  {GREEN}[OK] {message}{RESET}")


def warn(message: str) -> None:
    print(f"  {YELLOW}[WARN] {message}{RESET}")


def fail(message: str) -> None:
    print(f"  {RED}[ERR] {message}{RESET}")
    raise SystemExit(1)


def _npm_command() -> str:
    return "npm.cmd" if IS_WINDOWS else "npm"


def _write_runtime_state() -> None:
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps(
                {
                    "root_dir": str(ROOT_DIR),
                    "written_at": time.time(),
                    "processes": [
                        {"name": name, "pid": process.pid}
                        for name, process in PROCESSES
                        if process.poll() is None
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        warn(f"Failed to write runtime state: {exc}")


def _clear_runtime_state() -> None:
    try:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
        if RUNTIME_DIR.exists() and not any(RUNTIME_DIR.iterdir()):
            RUNTIME_DIR.rmdir()
    except OSError:
        pass


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


def _summarize_pip_output(output: str) -> list[str]:
    summary: list[str] = []
    normalized_lines = [line.strip() for line in output.splitlines() if line.strip()]

    if any("Defaulting to user installation because normal site-packages is not writeable" in line for line in normalized_lines):
        summary.append("site-packages 不可写，已自动切换到当前用户目录安装")

    installed_line = next(
        (
            line
            for line in reversed(normalized_lines)
            if line.startswith("Successfully installed ")
        ),
        None,
    )
    if installed_line:
        packages = installed_line.removeprefix("Successfully installed ").strip()
        if packages:
            summary.append(f"已安装: {packages}")

    return summary


def check_python() -> None:
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 9):
        fail(f"Python 3.9+ is required, current version is {major}.{minor}.")
    ok(f"Python {major}.{minor} ({sys.executable})")


def check_node() -> None:
    node_path = shutil.which("node")
    npm_path = shutil.which(_npm_command()) or shutil.which("npm")
    if not node_path or not npm_path:
        fail("Node.js and npm are required. Install them from https://nodejs.org first.")

    node_version = subprocess.check_output(["node", "--version"], text=True).strip()
    ok(f"Node.js {node_version}")


def ensure_python_dependencies() -> None:
    if not REQUIREMENTS_FILE.exists():
        warn("backend/requirements.txt is missing, skipping Python dependency check.")
        return

    missing: list[str] = []
    for package in _required_python_packages():
        try:
            __import__(_python_import_name(package))
        except ImportError:
            missing.append(package)

    if not missing:
        ok("Python dependencies are ready")
        return

    warn(f"Missing Python dependencies detected: {', '.join(missing)}")
    info("Auto-installing missing Python dependencies quietly...")
    result = subprocess.run(
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
        cwd=str(ROOT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    output = _decode_output_chunk(result.stdout or b"")
    if result.returncode != 0:
        warn("Automatic Python dependency installation failed.")
        tail_lines = [line for line in output.splitlines() if line.strip()][-20:]
        if tail_lines:
            print("")
            print(f"{YELLOW}{BOLD}[pip]{RESET}")
            for line in tail_lines:
                print(f"  {line}")
        fail(f"Please install dependencies manually: {sys.executable} -m pip install -r {REQUIREMENTS_FILE}")

    for line in _summarize_pip_output(output):
        info(line)
    ok("Python dependencies installed")


def ensure_node_dependencies() -> None:
    if NODE_MODULES_DIR.is_dir():
        ok("Node.js dependencies are ready")
        return

    warn("node_modules is missing, running npm install")
    subprocess.check_call([_npm_command(), "install"], cwd=str(ROOT_DIR))
    ok("Node.js dependencies installed")


def check_optional_dependencies() -> None:
    optional = [
        ("lancedb", "lancedb", "vector search"),
        ("fitz", "PyMuPDF", "PDF parsing"),
        ("docx", "python-docx", "Word parsing"),
        ("openpyxl", "openpyxl", "Excel parsing"),
    ]

    for module_name, package_name, capability in optional:
        try:
            __import__(module_name)
            ok(f"Optional dependency ready: {capability}")
        except ImportError:
            warn(f"Optional dependency missing: {capability}")
            info(f"Install with: pip install {package_name}")


def _decode_output_chunk(chunk: bytes) -> str:
    for encoding in OUTPUT_ENCODINGS:
        try:
            return chunk.decode(encoding)
        except UnicodeDecodeError:
            continue
    return chunk.decode("utf-8", errors="replace")


def _stream_output(process: subprocess.Popen, prefix: str, color: str) -> None:
    if process.stdout is None:
        return

    while True:
        line = process.stdout.readline()
        if not line:
            break
        print(f"{color}{BOLD}{prefix}{RESET} {_decode_output_chunk(line)}", end="", flush=True)


def _register_process(name: str, process: subprocess.Popen, color: str, prefix: str) -> subprocess.Popen:
    PROCESSES.append((name, process))
    _write_runtime_state()
    threading.Thread(target=_stream_output, args=(process, prefix, color), daemon=True).start()
    return process


def launch_backend() -> subprocess.Popen:
    process = subprocess.Popen(
        [
            sys.executable,
            "main.py",
            "--host",
            "127.0.0.1",
            "--port",
            "5173",
            "--reload",
        ],
        cwd=str(BACKEND_DIR),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0,
    )
    return _register_process("backend", process, BLUE, "[Backend]")


def launch_frontend() -> subprocess.Popen:
    process = subprocess.Popen(
        [_npm_command(), "run", "dev"],
        cwd=str(ROOT_DIR),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0,
    )
    return _register_process("frontend", process, GREEN, "[Frontend]")


def _format_signal(signum: int | None) -> str:
    if signum is None:
        return "manual request"
    try:
        return signal.Signals(signum).name
    except ValueError:
        return f"signal {signum}"


def _request_shutdown(reason: str) -> None:
    if SHUTDOWN_REQUESTED.is_set():
        FORCE_SHUTDOWN.set()
        warn(f"Additional stop request received ({reason}); forcing shutdown if needed.")
        return

    SHUTDOWN_REQUESTED.set()
    warn(f"Stop requested via {reason}. Shutting down services...")


def _handle_signal(signum: int, frame: object | None) -> None:
    del frame
    _request_shutdown(_format_signal(signum))


def _send_graceful_stop(name: str, process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return

    if IS_WINDOWS:
        ctrl_break = getattr(signal, "CTRL_BREAK_EVENT", None)
        if ctrl_break is not None:
            try:
                process.send_signal(ctrl_break)
                info(f"Sent Ctrl+Break to {name} (PID {process.pid})")
                return
            except Exception as exc:
                warn(f"Could not send Ctrl+Break to {name} (PID {process.pid}): {exc}")
        else:
            warn(f"Ctrl+Break is not available; {name} may need a forced stop.")
        return

    try:
        process.terminate()
        info(f"Sent terminate signal to {name} (PID {process.pid})")
    except Exception as exc:
        warn(f"Could not terminate {name} (PID {process.pid}): {exc}")


def _force_stop(name: str, process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return

    if IS_WINDOWS:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
        warn(f"Force-killed {name} (PID {process.pid})")
        return

    try:
        process.kill()
        warn(f"Force-killed {name} (PID {process.pid})")
    except Exception as exc:
        warn(f"Could not force-kill {name} (PID {process.pid}): {exc}")


def shutdown() -> None:
    global SHUTDOWN_DONE

    with SHUTDOWN_LOCK:
        if SHUTDOWN_DONE:
            return
        SHUTDOWN_DONE = True

    print(f"\n{YELLOW}{BOLD}Stopping all services...{RESET}")

    for name, process in PROCESSES:
        _send_graceful_stop(name, process)

    deadline = time.time() + 8.0
    while time.time() < deadline:
        alive = [process for _, process in PROCESSES if process.poll() is None]
        if not alive:
            break
        if FORCE_SHUTDOWN.is_set():
            break
        time.sleep(0.2)

    for name, process in PROCESSES:
        if process.poll() is None:
            _force_stop(name, process)

    _clear_runtime_state()
    print(f"{GREEN}Shutdown complete.{RESET}")


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

        command = line.strip().lower()
        if command in {"q", "quit", "exit", "stop"}:
            _request_shutdown("stdin command")
            return

        if command:
            info("Type q and press Enter to stop services.")


def _check_child_processes() -> None:
    for name, process in PROCESSES:
        exit_code = process.poll()
        if exit_code is None:
            continue
        if SHUTDOWN_REQUESTED.is_set():
            return
        _request_shutdown(f"{name} exited with code {exit_code}")
        return


def main() -> None:
    _enable_windows_ansi()

    print(f"\n{BOLD}{CYAN}{'=' * 60}{RESET}")
    print(f"{BOLD}{CYAN}  Meeting Assistant Development Launcher{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 60}{RESET}\n")

    print(f"{BOLD}1. Environment checks{RESET}")
    check_python()
    check_node()
    ensure_python_dependencies()
    ensure_node_dependencies()

    print(f"\n{BOLD}Optional capabilities{RESET}")
    check_optional_dependencies()

    print(f"\n{BOLD}2. Starting services{RESET}")
    info("Backend:  http://127.0.0.1:5173")
    info("Frontend: http://localhost:4173")

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)

    launch_backend()
    launch_frontend()

    threading.Thread(target=_watch_stdin_for_stop, daemon=True).start()

    print(f"\n{GREEN}{BOLD}[OK] Services are running.{RESET}")
    print(f"{CYAN}  Stop with Ctrl+C, Ctrl+Break, or type q then press Enter.{RESET}")
    print(f"{CYAN}  Fallback from another terminal: python scripts/dev/stop.py{RESET}\n")

    try:
        while not SHUTDOWN_REQUESTED.is_set():
            _check_child_processes()
            time.sleep(0.25)
    except KeyboardInterrupt:
        _request_shutdown("KeyboardInterrupt")
    finally:
        shutdown()
        raise SystemExit(0)


if __name__ == "__main__":
    main()
