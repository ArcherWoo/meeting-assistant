/**
 * Python FastAPI 后端进程管理器
 * 负责：启动/停止 Python 后端、端口分配、健康检查
 */
import { spawn, ChildProcess } from 'child_process';
import path from 'path';
import net from 'net';

export class PythonManager {
  private process: ChildProcess | null = null;
  private port: number = 0;
  private running = false;

  /** 获取一个可用的随机端口 */
  private async findFreePort(): Promise<number> {
    return new Promise((resolve, reject) => {
      const server = net.createServer();
      server.listen(0, () => {
        const addr = server.address();
        if (addr && typeof addr === 'object') {
          const port = addr.port;
          server.close(() => resolve(port));
        } else {
          reject(new Error('Failed to get port'));
        }
      });
      server.on('error', reject);
    });
  }

  /** 启动 Python FastAPI 后端 */
  async start(): Promise<void> {
    if (this.running) return;

    this.port = await this.findFreePort();
    const backendDir = path.join(__dirname, '..', 'backend');

    // 开发环境直接用 python，生产环境用打包的可执行文件
    // Windows 通常使用 'python'，macOS/Linux 使用 'python3'
    const devPythonCmd = process.platform === 'win32' ? 'python' : 'python3';
    const pythonCmd = process.env.VITE_DEV_SERVER_URL ? devPythonCmd : path.join(backendDir, 'meeting-assistant-backend');

    const args = process.env.VITE_DEV_SERVER_URL
      ? ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', String(this.port), '--reload']
      : ['--port', String(this.port)];

    this.process = spawn(pythonCmd, args, {
      cwd: backendDir,
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
    });

    // 日志输出
    this.process.stdout?.on('data', (data: Buffer) => {
      console.log(`[Python] ${data.toString().trim()}`);
    });
    this.process.stderr?.on('data', (data: Buffer) => {
      console.error(`[Python] ${data.toString().trim()}`);
    });
    this.process.on('exit', (code) => {
      console.log(`[Python] Process exited with code ${code}`);
      this.running = false;
    });

    // 等待后端就绪（健康检查轮询）
    await this.waitForReady();
    this.running = true;
  }

  /** 轮询健康检查接口，等待后端就绪 */
  private async waitForReady(maxRetries = 30, intervalMs = 200): Promise<void> {
    for (let i = 0; i < maxRetries; i++) {
      try {
        const response = await fetch(`http://127.0.0.1:${this.port}/api/health`);
        if (response.ok) return;
      } catch {
        // 后端尚未就绪，继续等待
      }
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
    throw new Error(`Python backend failed to start within ${(maxRetries * intervalMs) / 1000}s`);
  }

  /** 停止 Python 后端 */
  async stop(): Promise<void> {
    if (this.process) {
      if (process.platform === 'win32') {
        // Windows: 使用 taskkill 强制终止进程树
        const pid = this.process.pid;
        if (pid) {
          try {
            spawn('taskkill', ['/pid', String(pid), '/f', '/t'], { stdio: 'ignore' });
          } catch {
            this.process.kill();
          }
        }
      } else {
        // macOS/Linux: 使用 SIGTERM 优雅退出
        this.process.kill('SIGTERM');
        // 给进程 3 秒优雅退出时间
        await new Promise((resolve) => setTimeout(resolve, 3000));
        if (this.process && !this.process.killed) {
          this.process.kill('SIGKILL');
        }
      }
      this.process = null;
      this.running = false;
    }
  }

  getPort(): number {
    return this.port;
  }

  isRunning(): boolean {
    return this.running;
  }
}

