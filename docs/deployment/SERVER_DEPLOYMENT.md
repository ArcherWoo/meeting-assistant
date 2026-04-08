# 服务器部署说明

## 目标

这份文档对应当前 Phase 2 的服务器部署基线，目标是把项目收敛成两套统一入口：

- Windows：`deploy.ps1`
- Linux：`deploy.sh`

两套脚本都基于同一套 [deploy/](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/deploy) 逻辑，负责：

- 生成并校验 `deploy/server.env`
- 创建 `.server-venv/` 虚拟环境
- 安装后端依赖和前端依赖
- 构建前端到 `dist/`
- 启动生产服务
- 输出健康检查地址
- 生成可直接使用的 Nginx rendered 配置

## 当前推荐部署方式

### Windows

Windows 是当前优先部署形态，推荐方案：

1. 用 [deploy.ps1](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/deploy.ps1) 做一键部署
2. 后端由 [service_runner.py](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/deploy/service_runner.py) 托管
3. 用 Windows 计划任务实现开机自启
4. 前面接 Nginx 作为统一入口

当：

- `MEETING_ASSISTANT_RUNTIME_COORDINATION=sqlite`
- `MEETING_ASSISTANT_WORKERS > 1`

Windows 不再依赖 `uvicorn --workers`，而是自动切成“多实例单 worker”模式。

例如：

- `MEETING_ASSISTANT_PORT=5173`
- `MEETING_ASSISTANT_WORKERS=3`

则会启动：

- `127.0.0.1:5173`
- `127.0.0.1:5174`
- `127.0.0.1:5175`

再由 Nginx upstream 聚合成统一入口。

### Linux

Linux 仍保留同等能力，入口是 [deploy.sh](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/deploy.sh)。

推荐方案：

1. 用 `systemd` 托管服务
2. 前面接 Nginx
3. 对外只暴露统一站点入口，不直接暴露应用端口

## 开发脚本与生产脚本的职责区别

### 开发环境入口：`start.py`

[start.py](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/start.py) 是开发环境入口，适合本机联调，不适合服务器长期托管。

它现在会：

- 自动检查 Python 和 Node.js
- 自动安装缺失依赖
- 自动停止旧的开发进程
- 启动后端和前端
- 等待服务健康可用
- 输出 `智枢前端` 和 `后端接口` 的本机地址、局域网地址
- 启动失败时打印关键日志尾部

常用命令：

```bash
python start.py
python start.py --verbose
python start.py --skip-install
```

### 生产环境入口：`deploy.ps1 / deploy.sh`

生产脚本负责：

- 准备生产目录
- 创建 `.server-venv`
- 安装依赖
- 构建前端
- 生成 `deploy/server.env`
- 启动并托管服务
- 执行健康检查
- 输出部署结果、日志路径、访问地址
- 生成 rendered Nginx 配置

## 一键部署入口

### Windows

在管理员 PowerShell 中运行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deploy.ps1
```

如果只想前台运行，不注册计划任务：

```powershell
.\deploy.ps1 -Foreground
```

部署成功后脚本会输出：

- 存活检查地址
- 就绪检查地址
- 日志路径
- Nginx rendered 配置路径
- `智枢前端` 访问地址
- `后端接口` 地址
- `localhost` 和局域网地址，优先带出 `192.168.*`
- 如果已经安装 Nginx，还会自动接管 Nginx 配置并启动或重载

### Linux

先给脚本执行权限：

```bash
chmod +x deploy.sh
```

正常部署：

```bash
./deploy.sh
```

如果只想前台运行，不注册 `systemd`：

```bash
./deploy.sh --foreground
```

## 部署目录约定

脚本会自动创建并使用以下目录：

- `.server-venv/`
  - 生产环境 Python 虚拟环境
- `.server-data/`
  - 数据库、向量索引、日志、运行时数据
- `dist/`
  - 前端生产构建产物
- `deploy/server.env`
  - 生产环境配置文件

## 关键配置

主配置文件是 [deploy/server.env.example](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/deploy/server.env.example) 对应的实际副本：

- `deploy/server.env`

重点配置包括：

- 网络绑定：`MEETING_ASSISTANT_HOST`、`MEETING_ASSISTANT_PORT`
- 前端托管：`MEETING_ASSISTANT_SERVE_FRONTEND`、`MEETING_ASSISTANT_FRONTEND_DIST`
- 数据目录：`MEETING_ASSISTANT_HOME`、`MEETING_ASSISTANT_LOG_DIR`
- 日志：`MEETING_ASSISTANT_LOG_LEVEL`、`MEETING_ASSISTANT_LOG_FORMAT`
- 运行时协调：`MEETING_ASSISTANT_RUNTIME_COORDINATION`
- Python 覆盖：`MEETING_ASSISTANT_PYTHON_EXECUTABLE`
- 进程参数：`MEETING_ASSISTANT_WORKERS`、`MEETING_ASSISTANT_TIMEOUT_KEEP_ALIVE`、`MEETING_ASSISTANT_BACKLOG`
- 代理参数：`MEETING_ASSISTANT_PROXY_HEADERS`、`MEETING_ASSISTANT_FORWARDED_ALLOW_IPS`
- Uvicorn 限制：`MEETING_ASSISTANT_LIMIT_CONCURRENCY`、`MEETING_ASSISTANT_LIMIT_MAX_REQUESTS`

当前建议：

- `MEETING_ASSISTANT_RUNTIME_COORDINATION=sqlite`
- Windows 先从 `MEETING_ASSISTANT_WORKERS=2` 起压测
- Linux 先从 `MEETING_ASSISTANT_WORKERS=1` 或 `2` 起压测

## 健康检查与运行时诊断

服务启动后可用的诊断接口：

```text
/api/health
/api/health/live
/api/health/ready
/api/health/runtime
```

以默认端口 `5173` 为例：

```text
http://127.0.0.1:5173/api/health/live
http://127.0.0.1:5173/api/health/ready
http://127.0.0.1:5173/api/health/runtime
```

用途分别是：

- `live`
  - 进程是否活着
- `ready`
  - 存储、目录、前端构建是否准备好承接流量
- `runtime`
  - 运行时限额和当前占用快照

`/api/health/runtime` 当前会返回：

- LLM 并发占用
- 会话生成占用
- 附件解析占用
- 应用级指标
  - `chat / agent inflight`
  - `chat / agent` 成功数、失败数、拒绝数
  - `chat` 平均首字耗时、模型耗时、端到端耗时、检索耗时

## Nginx 配置

当前推荐使用 Nginx 做统一反向代理。

部署脚本会自动生成 rendered 配置，默认位于：

- Windows：
  - [deploy/nginx/rendered/meeting-assistant.windows.rendered.conf](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/deploy/nginx/rendered/meeting-assistant.windows.rendered.conf)
- Linux：
  - [deploy/nginx/rendered/meeting-assistant.linux.rendered.conf](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/deploy/nginx/rendered/meeting-assistant.linux.rendered.conf)

当前模板已经覆盖这些重点：

- 统一反向代理到本机应用
- chat SSE 关闭代理缓冲
- agent 流式执行关闭代理缓冲
- 长回答场景设置较长读取超时
- 请求体大小限制

### Windows 当前的自动化行为

如果服务器上已经安装了 Nginx，`deploy.ps1` 现在会自动：

- 检测 `nginx.exe`
- 复制 rendered 配置到 `conf\meeting-assistant.conf`
- 把 `include meeting-assistant.conf;` 接入主 `nginx.conf`
- 执行 `nginx -t`
- 启动或重载 Nginx
- 注册 `MeetingAssistantNginx` 开机启动任务

默认会尝试这些目录：

- `项目目录\nginx`
- `项目上级目录\nginx`
- `C:\nginx`
- `C:\tools\nginx`
- `C:\srv\meeting-assistant\nginx`
- `C:\Program Files\nginx`

如果你用了别的路径，可以在 `deploy/server.env` 中设置：

```env
MEETING_ASSISTANT_NGINX_HOME=C:\你的Nginx目录
```

## Windows Server + Nginx 最简步骤

如果你只想快速部署，可按下面的顺序做：

1. 安装 Python、Node.js、Git
2. 下载 Windows 版 Nginx zip 并解压
3. 拉取项目到服务器
4. 在管理员 PowerShell 中运行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deploy.ps1
```

5. 确保 Nginx 已安装在脚本能找到的位置，或在 `deploy/server.env` 中设置 `MEETING_ASSISTANT_NGINX_HOME`
6. 重新执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deploy.ps1
```

更完整的清单见根目录 [README.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/README.md)。

## 服务管理

### Windows

```powershell
Get-ScheduledTask -TaskName MeetingAssistant
Get-ScheduledTask -TaskName MeetingAssistantNginx
Start-ScheduledTask -TaskName MeetingAssistant
Stop-ScheduledTask -TaskName MeetingAssistant
```

### Linux

```bash
sudo systemctl status meeting-assistant
sudo systemctl restart meeting-assistant
journalctl -u meeting-assistant -f
```

## 优雅关闭

### Windows

不要直接在任务管理器里结束 Python 进程，也不要优先使用 `Stop-ScheduledTask` 做硬停。

推荐方式：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deploy.ps1 -Stop
```

如果要连 Nginx 一起优雅关闭：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deploy.ps1 -Stop -StopNginx
```

这条链路会：

- 在运行时控制目录写入停止标记
- 让 `service_runner` 检测到后主动停止所有子实例
- 等应用健康检查真正下线后再返回

### Linux

Linux 下 `systemd` 已经配置了 `KillSignal=SIGINT`，所以推荐直接：

```bash
./deploy.sh --stop
```

如果要连 Nginx 一起优雅关闭：

```bash
./deploy.sh --stop --stop-nginx
```

## 当前 Phase 2 已完成内容

- 健康检查：`live / ready / runtime`
- 运行时诊断：LLM、会话生成、附件解析快照
- 应用级指标：chat / agent inflight、成功数、失败数、拒绝数、平均耗时
- 结构化日志：chat / agent 主链路带 `request_id`
- 单机多实例 / 多 worker 协调
  - 会话生成锁
  - LLM 并发配额
  - 附件解析配额
  - 已切到 SQLite 租约协调
- 部署配置外置到 `deploy/server.env`
- Windows 和 Linux 两个统一入口脚本
- Nginx rendered 配置自动生成

## 当前边界

当前还要明确两个边界：

1. 现在的共享协调覆盖的是“单机、多个本地实例或多个本地 worker，共享同一个 SQLite”的场景
2. 数据库仍然是 SQLite

也就是说，Phase 2 解决的是：

- 部署形态
- 运行时探针
- 代理接入
- 参数治理
- 单机并发协调

还不是最终的分布式扩展方案。
