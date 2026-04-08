param(
  [switch]$Foreground,
  [switch]$Stop,
  [switch]$StopNginx
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile = Join-Path $RootDir "deploy\server.env"
$VenvPython = Join-Path $RootDir ".server-venv\Scripts\python.exe"
$RunnerScript = Join-Path $RootDir "deploy\service_runner.py"
$TaskName = "MeetingAssistant"
$NginxTaskName = "MeetingAssistantNginx"
$RenderedNginx = Join-Path $RootDir "deploy\nginx\rendered\meeting-assistant.windows.rendered.conf"

function Write-Info([string]$Message) { Write-Host "[INFO] $Message" }
function Write-Ok([string]$Message) { Write-Host "[OK] $Message" }
function Write-Warn([string]$Message) { Write-Host "[WARN] $Message" }
function Write-Err([string]$Message) { Write-Host "[ERR] $Message" }

function Get-PythonLauncher {
  if (Get-Command py -ErrorAction SilentlyContinue) { return @("py", "-3") }
  if (Get-Command python -ErrorAction SilentlyContinue) { return @("python") }
  throw "未检测到 Python。请先安装 Python 3.10+。"
}

function Read-EnvValue([string]$Key, [string]$Default = "") {
  if (-not (Test-Path $EnvFile)) { return $Default }
  foreach ($line in Get-Content $EnvFile) {
    if ($line -match '^\s*#') { continue }
    if ($line -match "^\s*$Key=(.*)$") {
      return $Matches[1].Trim()
    }
  }
  return $Default
}

function Wait-Health([string]$Url, [int]$TimeoutSec = 45) {
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      $null = Invoke-RestMethod -Method Get -Uri $Url -TimeoutSec 3
      return $true
    } catch {
      Start-Sleep -Milliseconds 1000
    }
  }
  return $false
}

function Wait-ServiceDown([string]$Url, [int]$TimeoutSec = 45) {
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      $null = Invoke-RestMethod -Method Get -Uri $Url -TimeoutSec 3
      Start-Sleep -Milliseconds 1000
    } catch {
      return $true
    }
  }
  return $false
}

function Show-LogTail([string]$Path, [string]$Label) {
  if (Test-Path $Path) {
    Write-Warn "$Label（最近 30 行）"
    Get-Content -LiteralPath $Path -Tail 30
  }
}

function Show-AppLogTails([string]$LogRoot) {
  $primary = Join-Path $LogRoot "app.log"
  Show-LogTail -Path $primary -Label "app.log"
  Get-ChildItem -Path $LogRoot -Filter "app-instance-*.log" -ErrorAction SilentlyContinue |
    Sort-Object Name |
    ForEach-Object {
      Show-LogTail -Path $_.FullName -Label $_.Name
    }
}

function Get-NetworkIpv4Addresses {
  $preferred = [System.Collections.Generic.List[string]]::new()
  $fallback = [System.Collections.Generic.List[string]]::new()
  foreach ($item in Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue) {
    $ip = $item.IPAddress
    if (-not $ip) { continue }
    if ($ip -eq "127.0.0.1") { continue }
    if ($ip.StartsWith("169.254.")) { continue }
    if ($ip.StartsWith("192.168.")) {
      if (-not $preferred.Contains($ip)) { $preferred.Add($ip) }
      continue
    }
    if ($ip.StartsWith("172.") -or $ip.StartsWith("10.")) {
      if (-not $preferred.Contains($ip)) { $preferred.Add($ip) }
      continue
    }
    if (-not $fallback.Contains($ip)) { $fallback.Add($ip) }
  }
  return @($preferred + $fallback)
}

function Show-ServiceEndpoints([string]$Host, [string]$Port, [switch]$UseProxyEntrypoint) {
  $frontendUrls = [System.Collections.Generic.List[string]]::new()
  $backendUrls = [System.Collections.Generic.List[string]]::new()

  $frontendSuffix = if ($UseProxyEntrypoint) { "/" } else { ":$Port/" }
  $backendSuffix = if ($UseProxyEntrypoint) { "/api" } else { ":$Port/api" }

  if ($Host -eq "0.0.0.0" -or $Host -eq "*" -or [string]::IsNullOrWhiteSpace($Host)) {
    $frontendUrls.Add("http://localhost$frontendSuffix")
    $backendUrls.Add("http://localhost$backendSuffix")
    foreach ($ip in Get-NetworkIpv4Addresses) {
      $frontendUrls.Add("http://$ip$frontendSuffix")
      $backendUrls.Add("http://$ip$backendSuffix")
    }
  } else {
    $frontendUrls.Add("http://$Host$frontendSuffix")
    $backendUrls.Add("http://$Host$backendSuffix")
  }

  Write-Host "智枢前端:"
  foreach ($url in $frontendUrls) {
    Write-Host "  $url"
  }
  Write-Host "后端接口:"
  foreach ($url in $backendUrls) {
    Write-Host "  $url"
  }
}

function Resolve-NginxHome {
  $configured = Read-EnvValue "MEETING_ASSISTANT_NGINX_HOME" ""
  $candidates = [System.Collections.Generic.List[string]]::new()

  if (-not [string]::IsNullOrWhiteSpace($configured)) {
    $candidates.Add($configured)
  }

  foreach ($candidate in @(
    (Join-Path $RootDir "nginx"),
    (Join-Path (Split-Path $RootDir -Parent) "nginx"),
    "C:\nginx",
    "C:\tools\nginx",
    "C:\srv\meeting-assistant\nginx",
    "C:\Program Files\nginx"
  )) {
    if (-not [string]::IsNullOrWhiteSpace($candidate) -and -not $candidates.Contains($candidate)) {
      $candidates.Add($candidate)
    }
  }

  foreach ($candidate in $candidates) {
    $exe = Join-Path $candidate "nginx.exe"
    if (Test-Path $exe) {
      return (Resolve-Path $candidate).Path
    }
  }

  return $null
}

function Ensure-NginxInclude([string]$NginxConfPath) {
  if (-not (Test-Path $NginxConfPath)) {
    throw "未找到 Nginx 主配置文件：$NginxConfPath"
  }

  $content = Get-Content -LiteralPath $NginxConfPath -Raw
  if ($content -match '(?im)include\s+meeting-assistant\.conf\s*;') {
    return
  }

  if ($content -notmatch 'http\s*\{') {
    throw "Nginx 主配置文件中没有找到 http 块，无法自动插入 include。"
  }

  $updated = $content -replace 'http\s*\{', "http {`r`n    include meeting-assistant.conf;"
  Set-Content -LiteralPath $NginxConfPath -Value $updated -Encoding UTF8
}

function Configure-Nginx([string]$NginxHome) {
  $nginxConfDir = Join-Path $NginxHome "conf"
  if (-not (Test-Path $nginxConfDir)) {
    throw "Nginx 目录下缺少 conf 目录：$nginxConfDir"
  }

  $targetConf = Join-Path $nginxConfDir "meeting-assistant.conf"
  Copy-Item -LiteralPath $RenderedNginx -Destination $targetConf -Force
  Ensure-NginxInclude -NginxConfPath (Join-Path $nginxConfDir "nginx.conf")
  return $targetConf
}

function Register-NginxTask([string]$NginxHome) {
  $nginxExe = Join-Path $NginxHome "nginx.exe"
  $action = New-ScheduledTaskAction -Execute $nginxExe -Argument "-p `"$NginxHome`" -c conf\nginx.conf" -WorkingDirectory $NginxHome
  $trigger = New-ScheduledTaskTrigger -AtStartup
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
  Register-ScheduledTask -TaskName $NginxTaskName -Action $action -Trigger $trigger -Settings $settings -User "SYSTEM" -RunLevel Highest -Force | Out-Null
}

function Start-OrReload-Nginx([string]$NginxHome) {
  $nginxExe = Join-Path $NginxHome "nginx.exe"
  & $nginxExe -p $NginxHome -c "conf\nginx.conf" -t | Out-Null

  $running = Get-Process nginx -ErrorAction SilentlyContinue
  if ($running) {
    & $nginxExe -p $NginxHome -c "conf\nginx.conf" -s reload | Out-Null
    return "已重载"
  }

  Start-Process -FilePath $nginxExe -ArgumentList @("-p", $NginxHome, "-c", "conf\nginx.conf") -WorkingDirectory $NginxHome | Out-Null
  Start-Sleep -Seconds 2
  return "已启动"
}

function Stop-NginxGracefully([string]$NginxHome) {
  $nginxExe = Join-Path $NginxHome "nginx.exe"
  if (-not (Test-Path $nginxExe)) {
    return $false
  }
  $running = Get-Process nginx -ErrorAction SilentlyContinue
  if (-not $running) {
    return $true
  }
  & $nginxExe -p $NginxHome -c "conf\nginx.conf" -s quit | Out-Null
  Start-Sleep -Seconds 2
  return -not (Get-Process nginx -ErrorAction SilentlyContinue)
}

function Request-GracefulStop([string]$ControlDir) {
  if (-not (Test-Path $ControlDir)) {
    New-Item -ItemType Directory -Path $ControlDir -Force | Out-Null
  }
  $stopFile = Join-Path $ControlDir "stop-requested"
  Set-Content -LiteralPath $stopFile -Value (Get-Date).ToString("s") -Encoding UTF8
  return $stopFile
}

$pythonLauncher = Get-PythonLauncher
$launcherArgs = @()
if ($pythonLauncher.Length -gt 1) {
  $launcherArgs = $pythonLauncher[1..($pythonLauncher.Length - 1)]
}

if ($Foreground) {
  & $pythonLauncher[0] @($launcherArgs | Where-Object { $_ }) (Join-Path $RootDir "deploy\deploy.py") "foreground" "--env-file" $EnvFile
  exit $LASTEXITCODE
}

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
  throw "请使用管理员 PowerShell 运行 deploy.ps1。"
}

$hostValue = Read-EnvValue "MEETING_ASSISTANT_HOST" "0.0.0.0"
$port = Read-EnvValue "MEETING_ASSISTANT_PORT" "5173"
$healthUrl = "http://127.0.0.1:$port/api/health/live"
$readyUrl = "http://127.0.0.1:$port/api/health/ready"
$runtimeHome = Read-EnvValue "MEETING_ASSISTANT_HOME" ".server-data"
if (-not [System.IO.Path]::IsPathRooted($runtimeHome)) {
  $runtimeHome = Join-Path $RootDir $runtimeHome
}
$controlDir = Join-Path $runtimeHome "control"
$runnerLog = Read-EnvValue "MEETING_ASSISTANT_LOG_DIR" ".server-data\logs"
if (-not [System.IO.Path]::IsPathRooted($runnerLog)) {
  $runnerLog = Join-Path $RootDir $runnerLog
}
$runnerLog = Join-Path $runnerLog "runner.log"
$logRoot = Split-Path $runnerLog -Parent

if ($Stop) {
  $stopFile = Request-GracefulStop -ControlDir $controlDir
  Write-Info "已发送优雅关闭请求：$stopFile"
  if (Wait-ServiceDown -Url $healthUrl -TimeoutSec 60) {
    Write-Ok "应用服务已优雅停止"
  } else {
    Write-Err "应用没有在预期时间内完成优雅关闭。"
    Show-LogTail -Path $runnerLog -Label "runner.log"
    exit 1
  }

  if ($StopNginx) {
    $nginxHome = Resolve-NginxHome
    if ($nginxHome) {
      if (Stop-NginxGracefully -NginxHome $nginxHome) {
        Write-Ok "Nginx 已优雅停止"
      } else {
        Write-Warn "Nginx 停止请求已发出，但仍检测到 nginx 进程。"
      }
    } else {
      Write-Warn "没有检测到 Nginx，已跳过 Nginx 停止步骤。"
    }
  }
  exit 0
}

Write-Info "准备生产环境"
& $pythonLauncher[0] @($launcherArgs | Where-Object { $_ }) (Join-Path $RootDir "deploy\deploy.py") "prepare" "--env-file" $EnvFile

$action = New-ScheduledTaskAction -Execute $VenvPython -Argument "`"$RunnerScript`" --env-file `"$EnvFile`""
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -User "SYSTEM" -RunLevel Highest -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Info "等待服务就绪：$healthUrl"
if (-not (Wait-Health -Url $healthUrl -TimeoutSec 60)) {
  Write-Err "服务没有在预期时间内启动成功。"
  Show-LogTail -Path $runnerLog -Label "runner.log"
  Show-AppLogTails -LogRoot $logRoot
  exit 1
}

if (-not (Wait-Health -Url $readyUrl -TimeoutSec 20)) {
  Write-Warn "存活检查已通过，但就绪检查暂未通过。你可以稍后手动查看：$readyUrl"
}

$nginxHome = Resolve-NginxHome
$nginxEnabled = $false
$nginxConfPath = $null
$nginxAction = $null

if ($nginxHome) {
  Write-Info "检测到 Nginx：$nginxHome"
  $nginxConfPath = Configure-Nginx -NginxHome $nginxHome
  Register-NginxTask -NginxHome $nginxHome
  $nginxAction = Start-OrReload-Nginx -NginxHome $nginxHome
  $nginxEnabled = $true
} else {
  Write-Warn "没有检测到可用的 nginx.exe。应用已部署成功，但还未接入 Nginx。"
  Write-Warn "如果你已经安装了 Nginx，请把它放到常见目录，或在 deploy/server.env 中设置 MEETING_ASSISTANT_NGINX_HOME 后重新执行 deploy.ps1。"
}

Write-Host ""
Write-Ok "Meeting Assistant 已完成 Windows 一键部署"
Write-Host "应用任务:         $TaskName"
Write-Host "存活检查:         $healthUrl"
Write-Host "就绪检查:         $readyUrl"
Write-Host "环境文件:         $EnvFile"
Write-Host "运行日志:         $runnerLog"
Write-Host "Rendered 配置:    $RenderedNginx"
if ($nginxEnabled) {
  Write-Host "Nginx 目录:       $nginxHome"
  Write-Host "Nginx 配置:       $nginxConfPath"
  Write-Host "Nginx 状态:       $nginxAction"
  Write-Host "Nginx 任务:       $NginxTaskName"
}
Write-Host ""
Show-ServiceEndpoints -Host $hostValue -Port $port -UseProxyEntrypoint:$nginxEnabled
Write-Host ""
Write-Host "常用命令:"
Write-Host "  查看应用任务: Get-ScheduledTask -TaskName $TaskName"
Write-Host "  启动应用任务: Start-ScheduledTask -TaskName $TaskName"
Write-Host "  优雅停止应用: .\deploy.ps1 -Stop"
Write-Host "  优雅停止应用和 Nginx: .\deploy.ps1 -Stop -StopNginx"
if ($nginxEnabled) {
  Write-Host "  查看 Nginx 任务: Get-ScheduledTask -TaskName $NginxTaskName"
}
