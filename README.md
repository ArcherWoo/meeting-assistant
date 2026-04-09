# Meeting Assistant

一个基于 `React + Vite + FastAPI` 的智能工作台，当前主线能力包括：

- 智能对话与流式输出
- 附件提取与上下文注入
- 知识库导入、检索与 RAG
- Skill / Know-how 管理
- Agent 执行模式
- 用户、用户组、权限与组内 Know-how 管理

## 项目结构

```text
.
├─ backend/               FastAPI 后端
├─ deploy/                生产部署核心逻辑
├─ docs/                  架构、开发、部署、产品文档
├─ scripts/               开发、压测、辅助脚本
├─ src/                   React 前端
├─ start.py               开发环境一键启动入口
├─ deploy.ps1             Windows 生产部署入口
├─ deploy.sh              Linux 生产部署入口
└─ package.json           前端脚本与依赖
```

更细的结构说明见 [docs/architecture/PROJECT_STRUCTURE.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/architecture/PROJECT_STRUCTURE.md)。

## 开发环境一键启动

在项目根目录运行：

```bash
python start.py
```

默认行为：

- 自动检查 Python 和 Node.js
- 自动安装前后端依赖
- 自动清理旧的开发进程
- 自动启动后端和前端
- 自动等待服务健康可用后再输出结果

启动成功后会输出：

- `智枢前端`
  - `Local: http://localhost:4173/`
  - `Network: http://192.168.x.x:4173/`
  - 以及其他可用局域网地址，例如 `172.*`
- `后端接口`
  - `http://localhost:5173/api`
  - 对应的局域网地址版本

常用参数：

```bash
python start.py --help
python start.py --verbose
python start.py --skip-install
python start.py --backend-port 5173 --frontend-port 4173
```

说明：

- 默认是安静模式，详细日志会写入 `.dev-runtime/logs/`
- 如果启动失败，脚本会自动打印关键日志尾部
- 如果环境异常，脚本会尽量自动修复并重新尝试

默认管理员账号：

| 字段 | 值 |
|------|----|
| 用户名 | `admin` |
| 密码 | `admin123` |

首次进入系统后请立即修改默认密码。

## 生产环境一键部署

当前生产部署分三条入口：

- Windows: [deploy.ps1](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/deploy.ps1)
- Windows CMD: [deploy.bat](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/deploy.bat)
- Linux: [deploy.sh](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/deploy.sh)

这两个脚本都基于同一套 [deploy/](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/deploy) 逻辑，负责：

- 生成并校验 `deploy/server.env`
- 创建 `.server-venv/`
- 安装后端依赖和前端依赖
- 构建前端到 `dist/`
- 启动生产服务
- 输出 `live / ready / runtime` 健康检查地址
- 生成 Nginx rendered 配置

### Windows Server + Nginx 傻瓜式部署清单

这套方案适合你的当前目标：`Windows Server + Nginx + FastAPI 单机多实例 + SQLite 协调`。

#### 1. 服务器先准备这些软件

请先在 Windows Server 上安装：

1. `Python 3.10+`
2. `Node.js 18+`
3. `Git`
4. `Nginx for Windows`

Nginx 建议下载：

- 官网地址：`https://nginx.org/en/download.html`
- 选择 `nginx/Windows` 稳定版 zip 包
- 下载后直接解压，不需要安装程序

#### 2. 建议目录

建议把项目和 Nginx 放在固定目录，例如：

```text
C:\srv\meeting-assistant\
  ├─ meeting-assistant-main\
  └─ nginx\
```

其中：

- 项目目录：`C:\srv\meeting-assistant\meeting-assistant-main`
- Nginx 目录：`C:\srv\meeting-assistant\nginx`

#### 3. 拉取项目

在 PowerShell 中执行：

```powershell
cd C:\srv\meeting-assistant
git clone <你的仓库地址> meeting-assistant-main
cd .\meeting-assistant-main
```

如果你不是用 Git，也可以直接把项目目录完整拷贝到这台服务器。

#### 4. 先生成生产配置

在管理员 PowerShell 中执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deploy.ps1 -Foreground
```

第一次这样跑的目的，是先让脚本自动完成：

- 创建 `.server-venv`
- 安装依赖
- 构建前端
- 生成 `deploy/server.env`
- 生成 rendered Nginx 配置

如果你不想让前台服务一直挂着，等看到“服务启动成功”后，按 `Ctrl + C` 停掉即可。

从这版开始，生产部署的 Python 依赖准备逻辑已经和 `python start.py` 对齐：

- `.server-venv` 默认会复用当前 Python 环境里已经可用的包
- 只会安装真正缺失的后端依赖，不再强制整包重装 `backend/requirements.txt`
- 如果公司镜像里缺少某个精确版本，会自动回退尝试安装该包的可用版本
- 如果服务器上残留的是旧版 `.server-venv`，且没有开启 `system-site-packages`，脚本会自动重建这个 venv

这对“只能使用公司内部镜像源”的服务器尤其重要，因为它能最大程度复用已经被验证可用、并且能直接跑通 `python start.py` 的 Python 环境。

而且默认不需要你手动先改 `deploy/server.env`：

- 首次执行 `.\deploy.ps1` 时，脚本会自动生成 `deploy/server.env`
- 会优先从当前机器已有的 pip 环境变量和 pip 配置里自动探测公司镜像
- 如果服务器上已经存在旧版 `deploy/server.env`，脚本也会自动回填这些镜像相关字段
- 只有在机器本身既没有可复用依赖、也没有可探测的 pip 镜像配置时，才需要你手工补配置

如果你是在 Windows Server 的 `cmd.exe` 里操作，也可以直接运行：

```bat
deploy.bat
```

它会自动转调 `deploy.ps1`，不需要你自己先切到 PowerShell。

#### 5. 修改生产配置

打开：

- [deploy/server.env](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/deploy/server.env)

至少检查这些项：

```env
MEETING_ASSISTANT_HOST=0.0.0.0
MEETING_ASSISTANT_PORT=5173
MEETING_ASSISTANT_WORKERS=2
MEETING_ASSISTANT_RUNTIME_COORDINATION=sqlite
MEETING_ASSISTANT_SERVE_FRONTEND=1
MEETING_ASSISTANT_FRONTEND_DIST=./dist
```

如果你的服务器只能访问公司内部 pip 镜像，再补上这些项：

```env
MEETING_ASSISTANT_VENV_SYSTEM_SITE_PACKAGES=1
MEETING_ASSISTANT_PIP_INDEX_URL=https://你的公司镜像/simple
MEETING_ASSISTANT_PIP_EXTRA_INDEX_URL=
MEETING_ASSISTANT_PIP_TRUSTED_HOST=你的公司镜像域名
MEETING_ASSISTANT_PIP_FIND_LINKS=
MEETING_ASSISTANT_PIP_NO_INDEX=
MEETING_ASSISTANT_PIP_ARGS=
```

说明：

- `MEETING_ASSISTANT_VENV_SYSTEM_SITE_PACKAGES=1` 建议保留开启
- 如果当前服务器上的 Python 已经能直接运行 `python start.py`，生产部署会优先复用这套已安装依赖
- 只有缺失的包才会走 pip 安装

Windows 单机建议起步值：

- `MEETING_ASSISTANT_WORKERS=2`
- 如果服务器配置更高，再逐步压测升到 `3` 或 `4`

#### 6. 正式注册生产服务

仍然在管理员 PowerShell 中执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deploy.ps1
```

如果你只使用 `cmd.exe`，等价命令是：

```bat
deploy.bat
```

它会自动：

- 注册计划任务 `MeetingAssistant`
- 用 `service_runner.py` 托管服务
- 自动做存活和就绪检查
- 输出日志位置和服务地址

#### 7. 让脚本自动接管 Nginx

现在的推荐方式是：只要服务器上已经安装好 Nginx，`deploy.ps1` 会自动完成这些事：

- 找到 `nginx.exe`
- 把 rendered 配置复制到 `conf\meeting-assistant.conf`
- 自动把 `include meeting-assistant.conf;` 接进主 `nginx.conf`
- 自动执行 `nginx -t`
- 自动启动或重载 Nginx

你只需要保证 Nginx 在这些位置之一：

- `项目目录\nginx`
- `项目上级目录\nginx`
- `C:\nginx`
- `C:\tools\nginx`
- `C:\srv\meeting-assistant\nginx`
- `C:\Program Files\nginx`

如果你放在别的位置，就在 [deploy/server.env](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/deploy/server.env) 里加：

```env
MEETING_ASSISTANT_NGINX_HOME=C:\你的Nginx目录
```

这样重新执行一次：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deploy.ps1
```

脚本就会自动把 Nginx 接好，不需要你再手工修改 `nginx.conf`。

#### 8. 如果你想手动检查 Nginx

虽然现在脚本会自动处理，但你也可以自己检查：

```powershell
cd C:\srv\meeting-assistant\nginx
.\nginx.exe -t
.\nginx.exe -s reload
```

#### 9. 最终访问方式

部署成功后：

- 应用服务仍然监听在 `5173` 起的一组本地端口
- 对外推荐通过 Nginx 暴露统一入口

示例：

- `http://服务器IP/`
- 或者你后续绑定域名后用 `http://你的域名/`

#### 10. 常用排查命令

查看计划任务：

```powershell
Get-ScheduledTask -TaskName MeetingAssistant
Get-ScheduledTask -TaskName MeetingAssistantNginx
```

手动启动：

```powershell
Start-ScheduledTask -TaskName MeetingAssistant
```

手动停止：

```powershell
Stop-ScheduledTask -TaskName MeetingAssistant
```

### 11. 优雅关闭生产环境

开发环境的 `start.py` 可以优雅关闭，生产环境现在也有正式的优雅关闭入口。

Windows：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deploy.ps1 -Stop
```

或者在 `cmd.exe` 里：

```bat
deploy.bat -Stop
```

如果连 Nginx 也一起优雅关闭：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deploy.ps1 -Stop -StopNginx
```

或者在 `cmd.exe` 里：

```bat
deploy.bat -Stop -StopNginx
```

说明：

- 这个动作不是直接硬杀进程
- 它会先给 `service_runner` 发停止请求
- `service_runner` 会自己优雅停止后端实例，再退出
- 这样更不容易留下端口占用

Linux：

```bash
./deploy.sh --prepare
./deploy.sh --foreground
```

以及：

```bash
./deploy.sh --stop
```

如果连 Nginx 也一起优雅关闭：

```bash
./deploy.sh --stop --stop-nginx
```

查看健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:5173/api/health/live
Invoke-RestMethod http://127.0.0.1:5173/api/health/ready
Invoke-RestMethod http://127.0.0.1:5173/api/health/runtime
```

查看日志目录：

- `.server-data\logs\runner.log`
- `.server-data\logs\app.log`
- `.server-data\logs\app-instance-*.log`

说明：

- 应用服务已经有进程守护，异常退出后会被自动拉起
- `deploy.ps1` 也会为 Nginx 注册开机启动任务

## 生产部署说明入口

更详细的生产部署说明见 [docs/deployment/SERVER_DEPLOYMENT.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/deployment/SERVER_DEPLOYMENT.md)。

## 文档导航

- 文档总导航：[docs/README.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/README.md)
- 开发说明：[docs/development/DEVELOPMENT.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/development/DEVELOPMENT.md)
- 项目结构：[docs/architecture/PROJECT_STRUCTURE.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/architecture/PROJECT_STRUCTURE.md)
- 服务端部署：[docs/deployment/SERVER_DEPLOYMENT.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/deployment/SERVER_DEPLOYMENT.md)
- 压测说明：[docs/deployment/LOAD_TESTING.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/deployment/LOAD_TESTING.md)
- 产品文档：[docs/product/PRD.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/product/PRD.md)
