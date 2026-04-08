from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from common import (
    BACKEND_DIR,
    DEFAULT_ENV_FILE,
    DEFAULT_VENV_DIR,
    ROOT_DIR,
    CommandExecutionError,
    command_exists,
    ensure_env_file,
    ensure_runtime_dirs,
    ensure_venv,
    get_venv_python,
    load_env_file,
    merge_env,
    print_block,
    print_error,
    print_info,
    print_ok,
    run,
    tail_text,
    is_windows,
)


def _npm_command() -> list[str]:
    return ["npm.cmd"] if is_windows() else ["npm"]


def _int_env(env: dict[str, str], key: str, default: int, *, minimum: int = 0) -> int:
    raw = str(env.get(key, "")).strip()
    if not raw:
      return default
    try:
      return max(minimum, int(raw))
    except ValueError:
      return default


def _frontend_dist(env_file: Path) -> Path:
    env = merge_env(env_file)
    return Path(env.get("MEETING_ASSISTANT_FRONTEND_DIST", str((ROOT_DIR / "dist").resolve()))).resolve()


def _render_nginx_config(env_file: Path, *, target_platform: str) -> Path:
    env = load_env_file(env_file)
    base_port = _int_env(env, "MEETING_ASSISTANT_PORT", 5173, minimum=1)
    workers = _int_env(env, "MEETING_ASSISTANT_WORKERS", 1, minimum=1)
    coordination_backend = env.get("MEETING_ASSISTANT_RUNTIME_COORDINATION", "memory").strip().lower() or "memory"
    upstream_host = "127.0.0.1"

    if target_platform == "windows" and coordination_backend == "sqlite" and workers > 1:
        ports = [base_port + index for index in range(workers)]
        worker_note = (
            f"# Windows 多实例模式：service_runner 会启动 {workers} 个单 worker 实例，"
            f"端口范围为 {ports[0]}-{ports[-1]}"
        )
    else:
        ports = [base_port]
        worker_note = "# 单入口模式：Nginx 代理到一个后端监听端口"

    upstream_lines = "\n".join(f"        server {upstream_host}:{port};" for port in ports)
    rendered = f"""worker_processes  1;

events {{
    worker_connections  2048;
}}

http {{
    include       mime.types;
    default_type  application/octet-stream;

    sendfile        on;
    keepalive_timeout  65;
    client_max_body_size 32m;

    {worker_note}
    upstream meeting_assistant_app {{
{upstream_lines}
        keepalive 32;
    }}

    server {{
        listen       80;
        server_name  localhost;

        location /api/chat/completions {{
            proxy_pass http://meeting_assistant_app;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_buffering off;
            proxy_cache off;
            proxy_read_timeout 3600s;
            proxy_send_timeout 3600s;
            proxy_set_header Connection "";
            add_header X-Accel-Buffering no;
        }}

        location /api/agent/execute {{
            proxy_pass http://meeting_assistant_app;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_buffering off;
            proxy_cache off;
            proxy_read_timeout 3600s;
            proxy_send_timeout 3600s;
            proxy_set_header Connection "";
            add_header X-Accel-Buffering no;
        }}

        location / {{
            proxy_pass http://meeting_assistant_app;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 120s;
            proxy_send_timeout 120s;
        }}
    }}
}}
"""
    output_dir = ROOT_DIR / "deploy" / "nginx" / "rendered"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"meeting-assistant.{target_platform}.rendered.conf"
    output_path.write_text(rendered, encoding="utf-8")
    return output_path


def _assert_prerequisites() -> None:
    if not command_exists("node"):
        raise RuntimeError("未检测到 Node.js。请先安装 Node.js 18+。")


def _run_step(label: str, command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print_info(f"{label}...")
    try:
        run(command, cwd=cwd, env=env, label=label)
        print_ok(f"{label}完成")
    except CommandExecutionError as exc:
        print_error(f"{label}失败")
        tail = tail_text(exc.output, lines=25)
        if tail:
            print_block("")
            print_block(tail)
        raise


def prepare(env_file: Path) -> None:
    _assert_prerequisites()
    ensure_env_file(env_file)
    runtime_dirs = ensure_runtime_dirs(env_file)
    ensure_venv(DEFAULT_VENV_DIR)
    venv_python = get_venv_python(DEFAULT_VENV_DIR)

    build_env = merge_env(env_file)
    build_env.setdefault("VITE_API_BASE_URL", "/api")

    print_block("")
    print_info("开始准备生产环境")
    print_info(f"环境文件: {env_file}")
    print_info(f"应用目录: {runtime_dirs['app_home']}")
    print_info(f"日志目录: {runtime_dirs['log_dir']}")

    _run_step(
        "升级 pip",
        [str(venv_python), "-m", "pip", "install", "--disable-pip-version-check", "--progress-bar", "off", "--upgrade", "pip"],
    )
    _run_step(
        "安装后端依赖",
        [str(venv_python), "-m", "pip", "install", "--disable-pip-version-check", "--progress-bar", "off", "-r", "backend/requirements.txt"],
    )
    _run_step(
        "安装前端依赖",
        [*_npm_command(), "install", "--no-fund", "--no-audit", "--loglevel=error"],
        cwd=ROOT_DIR,
    )
    _run_step(
        "构建前端",
        [*_npm_command(), "run", "build"],
        cwd=ROOT_DIR,
        env=build_env,
    )

    dist_dir = _frontend_dist(env_file)
    if not (dist_dir / "index.html").exists():
        raise RuntimeError(f"前端构建目录无效，缺少 index.html：{dist_dir}")

    windows_nginx = _render_nginx_config(env_file, target_platform="windows")
    linux_nginx = _render_nginx_config(env_file, target_platform="linux")
    port = build_env.get("MEETING_ASSISTANT_PORT", "5173")

    print_block("")
    print_ok("生产环境准备完成")
    print_block(f"Python 虚拟环境: {venv_python}")
    print_block(f"前端构建目录:   {dist_dir}")
    print_block(f"后端工作目录:   {BACKEND_DIR}")
    print_block(f"存活检查:       http://127.0.0.1:{port}/api/health/live")
    print_block(f"就绪检查:       http://127.0.0.1:{port}/api/health/ready")
    print_block(f"运行时诊断:     http://127.0.0.1:{port}/api/health/runtime")
    print_block(f"Windows Nginx:  {windows_nginx}")
    print_block(f"Linux Nginx:    {linux_nginx}")


def start_foreground(env_file: Path) -> int:
    prepare(env_file)
    venv_python = get_venv_python(DEFAULT_VENV_DIR)
    env = merge_env(env_file)
    command = [
        str(venv_python),
        str(ROOT_DIR / "deploy" / "service_runner.py"),
        "--env-file",
        str(env_file),
    ]
    print_block("")
    print_info("以前台模式启动生产服务")
    return subprocess.call(command, cwd=str(ROOT_DIR), env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description="Meeting Assistant 部署助手")
    parser.add_argument("command", choices=["prepare", "foreground"], nargs="?", default="prepare")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="部署环境文件路径")
    args = parser.parse_args()

    env_file = Path(args.env_file).expanduser().resolve()
    try:
        if args.command == "foreground":
            return start_foreground(env_file)
        prepare(env_file)
        return 0
    except CommandExecutionError as exc:
        print_error(f"{exc.label}执行失败，退出码 {exc.returncode}")
        return exc.returncode or 1
    except Exception as exc:  # noqa: BLE001
        print_error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
