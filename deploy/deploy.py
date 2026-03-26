from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from common import (
    BACKEND_DIR,
    DEFAULT_ENV_FILE,
    DEFAULT_VENV_DIR,
    ROOT_DIR,
    command_exists,
    ensure_env_file,
    ensure_runtime_dirs,
    ensure_venv,
    get_venv_python,
    is_windows,
    merge_env,
    run,
)


def _npm_command() -> list[str]:
    return ["npm.cmd"] if is_windows() else ["npm"]


def prepare(env_file: Path) -> None:
    if not command_exists("node"):
        raise RuntimeError("未检测到 Node.js，请先安装 Node.js 18+")

    ensure_env_file(env_file)
    ensure_runtime_dirs(env_file)
    ensure_venv(DEFAULT_VENV_DIR)
    venv_python = get_venv_python(DEFAULT_VENV_DIR)

    run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(venv_python), "-m", "pip", "install", "-r", "backend/requirements.txt"])
    run([*_npm_command(), "install"], cwd=ROOT_DIR)

    build_env = merge_env(env_file)
    build_env.setdefault("VITE_API_BASE_URL", "/api")
    run([*_npm_command(), "run", "build"], cwd=ROOT_DIR, env=build_env)

    print("")
    print("Deployment preparation completed.")
    print(f"Repo root:        {ROOT_DIR}")
    print(f"Backend cwd:      {BACKEND_DIR}")
    print(f"Virtualenv:       {DEFAULT_VENV_DIR}")
    print(f"Python:           {venv_python}")
    print(f"Frontend dist:    {ROOT_DIR / 'dist'}")
    print(f"Server env file:  {env_file}")


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
    return subprocess.call(command, cwd=str(ROOT_DIR), env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description="Meeting Assistant server deployment helper")
    parser.add_argument(
        "command",
        choices=["prepare", "foreground"],
        nargs="?",
        default="prepare",
    )
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE),
        help="Path to the deployment env file",
    )
    args = parser.parse_args()

    env_file = Path(args.env_file).expanduser().resolve()

    try:
        if args.command == "foreground":
            return start_foreground(env_file)
        prepare(env_file)
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"Deployment command failed: {exc}")
        return exc.returncode or 1
    except Exception as exc:  # noqa: BLE001
        print(f"Deployment failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
