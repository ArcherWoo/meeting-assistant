#!/usr/bin/env python3
"""
Development launcher for Meeting Assistant.

It validates the local environment, installs missing dependencies when needed,
then starts the backend and frontend dev servers together.
"""

from __future__ import annotations

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
PROCESSES: list[subprocess.Popen] = []

RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
BLUE = "\033[34m"


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
    }
    return overrides.get(package_name, package_name.replace("-", "_").lower())


def check_python() -> None:
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 9):
        fail(f"Python 3.9+ is required, current version is {major}.{minor}.")
    ok(f"Python {major}.{minor}")


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

    warn(f"Installing missing Python dependencies: {', '.join(missing)}")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)], cwd=str(ROOT_DIR))
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


def _stream_output(process: subprocess.Popen, prefix: str, color: str) -> None:
    if process.stdout is None:
        return

    for line in process.stdout:
        print(f"{color}{BOLD}{prefix}{RESET} {line}", end="", flush=True)


def launch_backend() -> subprocess.Popen:
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
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
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    PROCESSES.append(process)
    threading.Thread(target=_stream_output, args=(process, "[Backend]", BLUE), daemon=True).start()
    return process


def launch_frontend() -> subprocess.Popen:
    process = subprocess.Popen(
        [_npm_command(), "run", "dev"],
        cwd=str(ROOT_DIR),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0,
    )
    PROCESSES.append(process)
    threading.Thread(target=_stream_output, args=(process, "[Frontend]", GREEN), daemon=True).start()
    return process


def shutdown(signum: int | None = None, frame: object | None = None) -> None:
    print(f"\n{YELLOW}{BOLD}Stopping all services...{RESET}")
    for process in PROCESSES:
        if process.poll() is not None:
            continue
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
        else:
            process.terminate()

    time.sleep(1)

    for process in PROCESSES:
        if process.poll() is None:
            process.kill()

    print(f"{GREEN}Shutdown complete.{RESET}")
    raise SystemExit(0)


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

    signal.signal(signal.SIGINT, shutdown)
    if not IS_WINDOWS:
        signal.signal(signal.SIGTERM, shutdown)

    backend_process = launch_backend()
    launch_frontend()

    print(f"\n{GREEN}{BOLD}[OK] Services are running. Press Ctrl+C to stop.{RESET}\n")

    try:
        backend_process.wait()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()


if __name__ == "__main__":
    main()
