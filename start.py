#!/usr/bin/env python3
"""
Meeting Assistant — 一键启动脚本
同时启动后端（FastAPI/Uvicorn :8765）和前端（Vite/Electron :5173）
用法：python3 start.py
"""

import os
import sys
import subprocess
import threading
import signal
import shutil

# ─── ANSI 颜色 ────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"
BLUE   = "\033[34m"

def ok(msg):    print(f"  {GREEN}✅ {msg}{RESET}")
def warn(msg):  print(f"  {YELLOW}⚠️  {msg}{RESET}")
def err(msg):   print(f"  {RED}❌ {msg}{RESET}")
def info(msg):  print(f"  {CYAN}ℹ️  {msg}{RESET}")

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

    # 读取必需包名（去掉版本限定符）
    with open(REQUIREMENTS) as f:
        pkgs = [
            line.split("==")[0].split(">=")[0].split("<=")[0].strip()
            for line in f if line.strip() and not line.startswith("#")
        ]

    missing = []
    for pkg in pkgs:
        import_name = pkg.replace("-", "_").lower()
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
        subprocess.check_call(["npm", "install"], cwd=ROOT_DIR)
        ok("npm 依赖安装完成")
    else:
        ok("Node.js 依赖已就绪")


def check_optional_deps():
    """检测可选依赖（不阻塞）"""
    optional = {
        "lancedb":    "向量检索（RAG）",
        "fitz":       "PDF 解析（PyMuPDF）",
        "docx":       "Word 文档解析（python-docx）",
        "openpyxl":   "Excel 解析",
    }
    for mod, desc in optional.items():
        try:
            __import__(mod)
            ok(f"[可选] {desc}")
        except ImportError:
            warn(f"[可选] {desc} 未安装 — 相关功能不可用")
            info(f"可运行：pip install {mod if mod != 'fitz' else 'PyMuPDF'} {mod if mod != 'docx' else 'python-docx'}")


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
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
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
    proc = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=ROOT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
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
            p.terminate()
    # 给进程 3 秒优雅退出
    import time
    time.sleep(3)
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
    info("前端：http://localhost:5173   (Vite dev server + Electron)")

    # 注册 Ctrl+C 处理
    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    backend = launch_backend()
    frontend = launch_frontend()

    print(f"\n{GREEN}{BOLD}✅ 服务已启动！按 Ctrl+C 停止。{RESET}\n")

    # 等待任意进程退出，若退出则关闭全部
    try:
        backend.wait()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()


if __name__ == "__main__":
    main()

