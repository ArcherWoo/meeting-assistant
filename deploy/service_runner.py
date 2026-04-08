from __future__ import annotations

import argparse
import platform
import signal
import socket
import subprocess
import time
from dataclasses import dataclass
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
CHILD_PROCESSES: list[subprocess.Popen[str]] = []
STOP_REQUEST_FILE = "stop-requested"


@dataclass(frozen=True)
class ChildSpec:
    name: str
    port: int
    command: list[str]
    env: dict[str, str]
    log_file: Path


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    return normalized in {"1", "true", "yes", "on"}


def _int_env(env: dict[str, str], key: str, default: int, *, minimum: int = 0) -> int:
    raw = str(env.get(key, "")).strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _write_line(log_file: Path, message: str) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(f"[{_timestamp()}] {message}\n")


def _handle_stop(signum: int, _frame) -> None:
    global SHUTTING_DOWN
    SHUTTING_DOWN = True
    for process in list(CHILD_PROCESSES):
        if process.poll() is None:
            try:
                process.terminate()
            except Exception:  # noqa: BLE001
                pass


def _stop_requested(stop_file: Path, runner_log: Path) -> bool:
    global SHUTTING_DOWN
    if SHUTTING_DOWN:
        return True
    if stop_file.exists():
        SHUTTING_DOWN = True
        _write_line(runner_log, f"graceful stop requested via {stop_file}")
        return True
    return False


def _get_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _runtime_python(env: dict[str, str]) -> str:
    configured = env.get("MEETING_ASSISTANT_PYTHON_EXECUTABLE", "").strip()
    if configured:
        return configured
    ensure_venv(DEFAULT_VENV_DIR)
    return str(get_venv_python(DEFAULT_VENV_DIR))


def _build_uvicorn_command(
    *,
    runtime_python: str,
    host: str,
    port: int,
    log_level: str,
    workers: int,
    timeout_keep_alive: int,
    backlog: int,
    limit_concurrency: int,
    limit_max_requests: int,
    proxy_headers: bool,
    forwarded_allow_ips: str,
    enable_access_log: bool,
) -> list[str]:
    command = [
        runtime_python,
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        host,
        "--port",
        str(port),
        "--log-level",
        log_level,
        "--workers",
        str(workers),
        "--timeout-keep-alive",
        str(timeout_keep_alive),
        "--backlog",
        str(backlog),
    ]
    if proxy_headers:
        command.extend(["--proxy-headers", "--forwarded-allow-ips", forwarded_allow_ips])
    if not enable_access_log:
        command.append("--no-access-log")
    if limit_concurrency > 0:
        command.extend(["--limit-concurrency", str(limit_concurrency)])
    if limit_max_requests > 0:
        command.extend(["--limit-max-requests", str(limit_max_requests)])
    return command


def _windows_cluster_enabled(env: dict[str, str], workers: int, coordination_backend: str) -> bool:
    return (
        platform.system().lower() == "windows"
        and workers > 1
        and coordination_backend == "sqlite"
    )


def build_child_specs(env: dict[str, str], env_file: Path, runner_log: Path | None = None) -> list[ChildSpec]:
    runtime_python = _runtime_python(env)
    host = env.get("MEETING_ASSISTANT_HOST", "0.0.0.0")
    base_port = _int_env(env, "MEETING_ASSISTANT_PORT", 5173, minimum=1)
    log_level = env.get("MEETING_ASSISTANT_LOG_LEVEL", "info")
    workers = _int_env(env, "MEETING_ASSISTANT_WORKERS", 1, minimum=1)
    timeout_keep_alive = _int_env(env, "MEETING_ASSISTANT_TIMEOUT_KEEP_ALIVE", 30, minimum=5)
    backlog = _int_env(env, "MEETING_ASSISTANT_BACKLOG", 2048, minimum=128)
    limit_concurrency = _int_env(env, "MEETING_ASSISTANT_LIMIT_CONCURRENCY", 0, minimum=0)
    limit_max_requests = _int_env(env, "MEETING_ASSISTANT_LIMIT_MAX_REQUESTS", 0, minimum=0)
    proxy_headers = _truthy(env.get("MEETING_ASSISTANT_PROXY_HEADERS"), default=True)
    forwarded_allow_ips = env.get("MEETING_ASSISTANT_FORWARDED_ALLOW_IPS", "127.0.0.1").strip() or "127.0.0.1"
    enable_access_log = _truthy(env.get("MEETING_ASSISTANT_ENABLE_ACCESS_LOG"), default=False)
    coordination_backend = env.get("MEETING_ASSISTANT_RUNTIME_COORDINATION", "memory").strip().lower() or "memory"
    log_dir = Path(env.get("MEETING_ASSISTANT_LOG_DIR", str((ROOT_DIR / ".server-data" / "logs").resolve()))).expanduser()
    if not log_dir.is_absolute():
        log_dir = (ROOT_DIR / log_dir).resolve()

    if workers > 1 and coordination_backend != "sqlite":
        if runner_log is not None:
            _write_line(
                runner_log,
                f"MEETING_ASSISTANT_WORKERS={workers} requested, but runtime coordination backend={coordination_backend}; falling back to a single instance.",
            )
        workers = 1

    shared_env = dict(env)
    shared_env["MEETING_ASSISTANT_SERVE_FRONTEND"] = env.get("MEETING_ASSISTANT_SERVE_FRONTEND", "1")
    shared_env["MEETING_ASSISTANT_FRONTEND_DIST"] = env.get(
        "MEETING_ASSISTANT_FRONTEND_DIST",
        str((ROOT_DIR / "dist").resolve()),
    )
    shared_env["MEETING_ASSISTANT_ENV_FILE"] = str(env_file)

    specs: list[ChildSpec] = []
    if _windows_cluster_enabled(shared_env, workers, coordination_backend):
        for index in range(workers):
            port = base_port + index
            child_env = dict(shared_env)
            child_env["MEETING_ASSISTANT_PORT"] = str(port)
            child_env["MEETING_ASSISTANT_INSTANCE_INDEX"] = str(index)
            child_env["MEETING_ASSISTANT_INSTANCE_COUNT"] = str(workers)
            child_env["MEETING_ASSISTANT_INSTANCE_MODE"] = "windows-cluster"
            command = _build_uvicorn_command(
                runtime_python=runtime_python,
                host=host,
                port=port,
                log_level=log_level,
                workers=1,
                timeout_keep_alive=timeout_keep_alive,
                backlog=backlog,
                limit_concurrency=limit_concurrency,
                limit_max_requests=limit_max_requests,
                proxy_headers=proxy_headers,
                forwarded_allow_ips=forwarded_allow_ips,
                enable_access_log=enable_access_log,
            )
            specs.append(
                ChildSpec(
                    name=f"instance-{index + 1}",
                    port=port,
                    command=command,
                    env=child_env,
                    log_file=log_dir / f"app-instance-{index + 1}.log",
                )
            )
        return specs

    command = _build_uvicorn_command(
        runtime_python=runtime_python,
        host=host,
        port=base_port,
        log_level=log_level,
        workers=workers,
        timeout_keep_alive=timeout_keep_alive,
        backlog=backlog,
        limit_concurrency=limit_concurrency,
        limit_max_requests=limit_max_requests,
        proxy_headers=proxy_headers,
        forwarded_allow_ips=forwarded_allow_ips,
        enable_access_log=enable_access_log,
    )
    shared_env["MEETING_ASSISTANT_INSTANCE_INDEX"] = "0"
    shared_env["MEETING_ASSISTANT_INSTANCE_COUNT"] = "1"
    shared_env["MEETING_ASSISTANT_INSTANCE_MODE"] = "single-process"
    return [
        ChildSpec(
            name="primary",
            port=base_port,
            command=command,
            env=shared_env,
            log_file=log_dir / "app.log",
        )
    ]


def _print_banner(host: str, ports: list[int]) -> None:
    green = "\033[92m"
    cyan = "\033[96m"
    bold = "\033[1m"
    reset = "\033[0m"

    display_host = _get_local_ip() if host in ("0.0.0.0", "::") else host
    border = "=" * 60
    print(f"\n{green}{border}{reset}")
    print(f"{bold}  Meeting Assistant Server Runner{reset}")
    print(f"{green}{border}{reset}")
    if len(ports) == 1:
        print(f"  {cyan}服务地址: {bold}http://{display_host}:{ports[0]}{reset}")
    else:
        joined_ports = ", ".join(str(port) for port in ports)
        print(f"  {cyan}入口地址: {bold}http://{display_host}:{ports[0]}{reset}")
        print(f"  Windows 多实例模式端口: {joined_ports}")
    if host in ("0.0.0.0", "::"):
        print(f"  正在监听所有网卡接口 ({host})")
    print(f"{green}{border}{reset}\n")


def _start_children(specs: list[ChildSpec], runner_log: Path) -> list[subprocess.Popen[str]]:
    processes: list[subprocess.Popen[str]] = []
    global CHILD_PROCESSES
    for spec in specs:
        _write_line(runner_log, f"starting {spec.name}: {' '.join(spec.command)}")
        output = spec.log_file.open("a", encoding="utf-8")
        process = subprocess.Popen(
            spec.command,
            cwd=str(BACKEND_DIR),
            env=spec.env,
            stdout=output,
            stderr=subprocess.STDOUT,
            text=True,
        )
        process._meeting_assistant_output = output  # type: ignore[attr-defined]
        processes.append(process)
    CHILD_PROCESSES = processes
    return processes


def _stop_children(processes: list[subprocess.Popen[str]], runner_log: Path) -> None:
    for process in processes:
        if process.poll() is None:
            try:
                process.terminate()
            except Exception:  # noqa: BLE001
                pass

    for process in processes:
        try:
            process.wait(timeout=15)
        except Exception:  # noqa: BLE001
            try:
                process.kill()
            except Exception:  # noqa: BLE001
                pass
        output = getattr(process, "_meeting_assistant_output", None)
        if output is not None:
            try:
                output.close()
            except Exception:  # noqa: BLE001
                pass
    _write_line(runner_log, "all child processes stopped")


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
    stop_file = paths["control_dir"] / STOP_REQUEST_FILE
    stop_file.unlink(missing_ok=True)

    signal.signal(signal.SIGINT, _handle_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_stop)

    specs = build_child_specs(env, env_file, runner_log)
    host = env.get("MEETING_ASSISTANT_HOST", "0.0.0.0")
    _print_banner(host, [spec.port for spec in specs])
    _write_line(runner_log, f"runner started, env={env_file}")

    while not SHUTTING_DOWN:
        processes = _start_children(specs, runner_log)

        while not SHUTTING_DOWN:
            if _stop_requested(stop_file, runner_log):
                break
            exited = [(spec, process.poll()) for spec, process in zip(specs, processes) if process.poll() is not None]
            if exited:
                for spec, exit_code in exited:
                    _write_line(runner_log, f"{spec.name} exited with code {exit_code}")
                break
            time.sleep(1)

        _stop_children(processes, runner_log)
        CHILD_PROCESSES.clear()

        if SHUTTING_DOWN:
            break

        _write_line(runner_log, f"child exit detected, restarting all instances in {restart_delay}s")
        time.sleep(restart_delay)

    stop_file.unlink(missing_ok=True)
    _write_line(runner_log, "runner stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
