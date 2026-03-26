param(
  [switch]$Foreground
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile = Join-Path $RootDir "deploy\server.env"
$VenvPython = Join-Path $RootDir ".server-venv\Scripts\python.exe"
$RunnerScript = Join-Path $RootDir "deploy\service_runner.py"
$TaskName = "MeetingAssistant"

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

function Get-PythonLauncher {
  if (Get-Command py -ErrorAction SilentlyContinue) {
    return @("py", "-3")
  }
  if (Get-Command python -ErrorAction SilentlyContinue) {
    return @("python")
  }
  throw "未检测到 Python，请先安装 Python 3.9+"
}

$pythonLauncher = Get-PythonLauncher
$launcherArgs = @()
if ($pythonLauncher.Length -gt 1) {
  $launcherArgs = $pythonLauncher[1..($pythonLauncher.Length - 1)]
}

if ($Foreground) {
  & $pythonLauncher[0] @($launcherArgs | Where-Object { $_ }) `
    (Join-Path $RootDir "deploy\deploy.py") "foreground" "--env-file" $EnvFile
  exit $LASTEXITCODE
}

if (-not $isAdmin) {
  throw "请用管理员 PowerShell 运行 deploy.ps1，脚本需要注册开机自启任务。"
}

& $pythonLauncher[0] @($launcherArgs | Where-Object { $_ }) `
  (Join-Path $RootDir "deploy\deploy.py") "prepare" "--env-file" $EnvFile

$action = New-ScheduledTaskAction -Execute $VenvPython -Argument "`"$RunnerScript`" --env-file `"$EnvFile`""
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -RestartCount 999 `
  -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -User "SYSTEM" `
  -RunLevel Highest `
  -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName

Write-Host ""
Write-Host "Meeting Assistant 已部署为 Windows 开机自启任务。"
Write-Host "任务名: $TaskName"
Write-Host "查看:   Get-ScheduledTask -TaskName $TaskName"
Write-Host "启动:   Start-ScheduledTask -TaskName $TaskName"
Write-Host "停止:   Stop-ScheduledTask -TaskName $TaskName"
