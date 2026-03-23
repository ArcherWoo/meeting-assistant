#!/usr/bin/env python3
"""
Meeting Assistant — 一键启动脚本
同时启动后端（FastAPI/Uvicorn :8765）和前端（Vite :5173）
用法：python start.py  或  python3 start.py
"""

import os
import sys
import subprocess
import threading
import signal
import shutil
import platform

IS_WINDOWS = platform.system() == "Windows"

# ─── ANSI 颜色（Windows 需启用虚拟终端序列） ──────────────────
def _enable_windows_ansi():
    """在 Windows 上启用 ANSI 转义码支持"""
    if not IS_WINDOWS:
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # STD_OUTPUT_HANDLE = -11
        handle = kernel32.GetStdHandle(-11)
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass  # 降级为无颜色输出

_enable_windows_ansi()

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"
BLUE   = "\033[34m"

def ok(msg):    print(f"  {GREEN}[OK] {msg}{RESET}")
def warn(msg):  print(f"  {YELLOW}[WARN] {msg}{RESET}")
def err(msg):   print(f"  {RED}[ERR] {msg}{RESET}")
def info(msg):  print(f"  {CYAN}[INFO] {msg}{RESET}")

# ─── 项目路径 ──────────────────────────────────────────────────
ROOT_DIR    = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
REQUIREMENTS = os.path.join(BACKEND_DIR, "requirements.txt")
NODE_MODULES = os.path.join(ROOT_DIR, "node_modules")

# ─── 全局进程句柄（供 Ctrl+C 清理） ───────────────────────────
_procs: list[subprocess.Popen] = []


# ══════════════════════════════════════════════════════════════
#  环境检测
# ══════════════════════════════════════════════════════════════

def check_python():
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 9):
        err(f"需要 Python ≥ 3.9，当前版本 {major}.{minor}")
        sys.exit(1)
    ok(f"Python {major}.{minor}")


def check_node():
    node = shutil.which("node")
    npm  = shutil.which("npm")
    if not node or not npm:
        err("未检测到 Node.js / npm，请前往 https://nodejs.org 手动安装后重试")
        sys.exit(1)
    node_ver = subprocess.check_output(["node", "--version"], text=True).strip()
    ok(f"Node.js {node_ver}  /  npm")


def check_python_deps():
    """检测 requirements.txt 中的核心依赖，缺失则自动安装"""
    if not os.path.exists(REQUIREMENTS):
        warn("未找到 backend/requirements.txt，跳过 Python 依赖检测")
        return

    # 读取必需包名（去掉版本限定符和 extras 后缀，如 uvicorn[standard] → uvicorn）
    with open(REQUIREMENTS) as f:
        pkgs = [
            line.split("==")[0].split(">=")[0].split("<=")[0].split("[")[0].strip()
            for line in f if line.strip() and not line.startswith("#")
        ]

    # pip 包名与 import 名不一致的映射表
    _IMPORT_OVERRIDES = {
        "python-pptx":      "pptx",
        "python-multipart":  "multipart",
    }

    missing = []
    for pkg in pkgs:
        import_name = _IMPORT_OVERRIDES.get(pkg, pkg.replace("-", "_").lower())
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg)

    if missing:
        warn(f"缺少 Python 依赖：{', '.join(missing)}，正在自动安装…")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", REQUIREMENTS],
            cwd=ROOT_DIR
        )
        ok("Python 依赖安装完成")
    else:
        ok("Python 依赖已就绪")


def check_node_deps():
    """检测 node_modules，缺失则自动 npm install"""
    if not os.path.isdir(NODE_MODULES):
        warn("node_modules/ 不存在，正在运行 npm install…")
        # Windows 上 npm 是 npm.cmd（批处理文件），需要 shell=True 才能正确执行
        subprocess.check_call("npm install", cwd=ROOT_DIR, shell=True)
        ok("npm 依赖安装完成")
    else:
        ok("Node.js 依赖已就绪")


def check_optional_deps():
    """检测可选依赖（不阻塞）"""
    # (import_name, pip_package, description)
    optional = [
        ("lancedb",  "lancedb",     "向量检索（RAG）"),
        ("fitz",     "PyMuPDF",     "PDF 解析（PyMuPDF）"),
        ("docx",     "python-docx", "Word 文档解析（python-docx）"),
        ("openpyxl", "openpyxl",    "Excel 解析"),
    ]
    for mod, pip_name, desc in optional:
        try:
            __import__(mod)
            ok(f"[可选] {desc}")
        except ImportError:
            warn(f"[可选] {desc} 未安装 -- 相关功能不可用")
            info(f"可运行：pip install {pip_name}")


# ══════════════════════════════════════════════════════════════
#  进程启动与日志转发
# ══════════════════════════════════════════════════════════════

def _stream_output(proc: subprocess.Popen, prefix: str, color: str):
    """将子进程的 stdout/stderr 转发到控制台（带颜色前缀）"""
    for line in proc.stdout:  # type: ignore[union-attr]
        print(f"{color}{BOLD}{prefix}{RESET} {line}", end="", flush=True)


def launch_backend() -> subprocess.Popen:
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "main:app",
            "--host", "127.0.0.1",
            "--port", "8765",
            "--reload",
        ],
        cwd=BACKEND_DIR,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    _procs.append(proc)
    t = threading.Thread(
        target=_stream_output,
        args=(proc, "[Backend]", BLUE),
        daemon=True,
    )
    t.start()
    return proc


def launch_frontend() -> subprocess.Popen:
    # Windows 上 npm 是 npm.cmd，需要 shell=True 才能找到
    npm_cmd = "npm" if not IS_WINDOWS else "npm.cmd"
    proc = subprocess.Popen(
        [npm_cmd, "run", "dev"],
        cwd=ROOT_DIR,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        shell=IS_WINDOWS,
        # 在独立进程组中启动：Ctrl+C 不会传递给 CMD，
        # CMD 永远不会触发"终止批处理作业"逻辑，彻底消除 GBK 乱码
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0,
    )
    _procs.append(proc)
    t = threading.Thread(
        target=_stream_output,
        args=(proc, "[Frontend]", GREEN),
        daemon=True,
    )
    t.start()
    return proc


def shutdown(signum=None, frame=None):
    print(f"\n{YELLOW}{BOLD}正在停止所有服务…{RESET}")
    for p in _procs:
        if p.poll() is None:
            if IS_WINDOWS:
                # taskkill /F /T 递归终止整个进程树（含独立进程组中的 node.exe 子进程）
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(p.pid)],
                    capture_output=True,
                )
            else:
                p.terminate()
    import time
    time.sleep(1)
    for p in _procs:
        if p.poll() is None:
            p.kill()
    print(f"{GREEN}已退出。再见！{RESET}")
    sys.exit(0)


# ══════════════════════════════════════════════════════════════
#  入口
# ══════════════════════════════════════════════════════════════

def main():
    print(f"\n{BOLD}{CYAN}{'═' * 54}{RESET}")
    print(f"{BOLD}{CYAN}   🤝  Meeting Assistant — 开发环境启动器{RESET}")
    print(f"{BOLD}{CYAN}{'═' * 54}{RESET}\n")

    print(f"{BOLD}【1/2】环境检测{RESET}")
    check_python()
    check_node()
    check_python_deps()
    check_node_deps()

    print(f"\n{BOLD}【可选依赖】{RESET}")
    check_optional_deps()

    print(f"\n{BOLD}【2/2】启动服务{RESET}")
    info("后端：http://127.0.0.1:8765   (FastAPI + uvicorn --reload)")
    info("前端：http://localhost:5173  /  http://127.0.0.1:5173   (Vite dev server)")

    # 注册 Ctrl+C 处理（Windows 不支持 SIGTERM）
    signal.signal(signal.SIGINT, shutdown)
    if not IS_WINDOWS:
        signal.signal(signal.SIGTERM, shutdown)

    backend = launch_backend()
    frontend = launch_frontend()

    print(f"\n{GREEN}{BOLD}[OK] 服务已启动！按 Ctrl+C 停止。{RESET}\n")

    # 等待任意进程退出，若退出则关闭全部
    try:
        backend.wait()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()


if __name__ == "__main__":
    main()

