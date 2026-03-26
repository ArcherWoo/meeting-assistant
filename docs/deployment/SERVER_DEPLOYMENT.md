# 服务器部署说明

## 这次做了什么

这个项目现在已经支持一套真正适合服务器的部署方式，不再依赖原来的 `start.py` 开发脚本。

- `start.py`
  - 仍然只用于本地开发
  - 启动前端开发服务器和后端热重载服务
- 生产部署
  - 前端先构建到 `dist/`
  - FastAPI 直接托管前端静态文件和 `/api`
  - 内置守护器负责异常退出后自动拉起
  - 提供 Linux 和 Windows Server 的一键部署脚本

## 直接回答

### 1. `start.py` 够不够

不够。

`start.py` 是开发环境启动器，不是生产环境启动器。

原因：

- 它启动的是 Vite 开发服务器，不是编译后的静态资源
- 它使用的是开发态热重载方式
- 它依赖交互式终端窗口常驻
- 它不会注册系统服务或开机自启

### 2. 要不要进程守护

要。

现在生产部署使用 [deploy/service_runner.py](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/deploy/service_runner.py) 作为应用级守护器：

- 负责启动 FastAPI
- 子进程异常退出后等待几秒自动重启
- 日志写入 `.server-data/logs/`

在这之上还叠加系统级托管：

- Linux 使用 `systemd`
- Windows Server 使用计划任务并以 `SYSTEM` 身份运行

这样既能自动重启，也能开机自动启动。

### 3. 前端是不是要改成公网 IP + 端口

不应该在代码里硬编码公网 IP。

现在前端默认走相对路径 `/api`，所以生产环境推荐：

- 用户直接访问 `http://你的服务器IP:5173`
- 前端页面和后端接口由同一个服务、同一个端口提供
- 以后如果要接 Nginx / IIS / HTTPS，也更容易扩展

这种方式比把公网 IP 写死在前端代码里更稳、更通用。

## 一键部署命令

### Linux

在有 `sudo` 权限的用户下运行：

```bash
chmod +x deploy.sh
./deploy.sh
```

如果只想以前台方式运行，不注册系统服务：

```bash
./deploy.sh --foreground
```

### Windows Server

在“管理员 PowerShell”里运行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deploy.ps1
```

如果只想以前台方式运行，不注册开机任务：

```powershell
.\deploy.ps1 -Foreground
```

## 默认运行目录

部署脚本会自动创建并使用这些目录：

- `.server-venv/`
  - 独立 Python 虚拟环境
- `.server-data/`
  - 数据库、向量索引、用户 Skill、日志
- `deploy/server.env`
  - 部署配置文件

## 主要配置文件

首次部署时会自动生成：

- `deploy/server.env`

关键配置项：

- `MEETING_ASSISTANT_HOST=0.0.0.0`
- `MEETING_ASSISTANT_PORT=5173`
- `MEETING_ASSISTANT_SERVE_FRONTEND=1`
- `MEETING_ASSISTANT_FRONTEND_DIST=.../dist`
- `MEETING_ASSISTANT_HOME=.../.server-data`
- `MEETING_ASSISTANT_LOG_DIR=.../.server-data/logs`

## 访问方式

部署完成后，默认访问地址：

```text
http://<server-ip>:5173
```

健康检查接口：

```text
http://<server-ip>:5173/api/health
```

补充说明：

- `4173` 只用于本地开发时的 Vite 前端开发服务器
- 服务器部署默认只对外提供 `5173`
- 也就是说，部署后用户只需要访问一个端口，不需要分别访问前后端

## 服务管理

### Linux

```bash
sudo systemctl status meeting-assistant
sudo systemctl restart meeting-assistant
journalctl -u meeting-assistant -f
```

### Windows Server

```powershell
Get-ScheduledTask -TaskName MeetingAssistant
Start-ScheduledTask -TaskName MeetingAssistant
Stop-ScheduledTask -TaskName MeetingAssistant
```

## 推荐的下一步升级

现在这套代码已经可以直接部署到服务器上。如果你要进一步做更正式的生产化，建议下一步补上：

1. Linux 侧接 Nginx，Windows 侧接 IIS/ARR
2. 在反向代理层处理 HTTPS
3. 让外部走 `80/443`，内部转发到应用端口 `5173`
