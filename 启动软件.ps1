param(
    [switch]$NoBrowser,
    [ValidateRange(1024,65000)][int]$PreferredPort = 8765
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$taskPythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPythonPath)) { throw '请先按 README.md 安装 Python 环境。' }
$taskIdentity = (& $taskPythonPath -m backend.runtime_identity | ConvertFrom-Json)
if ($LASTEXITCODE -ne 0 -or -not $taskIdentity.build_id) { throw '无法读取软件构建版本。' }
$taskSelectedPort = $null
$taskNeedsStart = $false
foreach ($taskPort in $PreferredPort..($PreferredPort+50)) {
    if (Get-NetTCPConnection -LocalPort $taskPort -State Listen -ErrorAction SilentlyContinue) {
        try {
            $taskRunning = Invoke-RestMethod "http://127.0.0.1:$taskPort/api/runtime" -TimeoutSec 1
            if ($taskRunning.service -eq 'terminal-power-platform' -and $taskRunning.build_id -eq $taskIdentity.build_id) {
                $taskSelectedPort = $taskPort
                break
            }
        } catch { }
    } else {
        $taskSelectedPort = $taskPort
        $taskNeedsStart = $true
        break
    }
}
if ($null -eq $taskSelectedPort) { throw '本地候选端口均已占用，请稍后再试。' }
$taskUrl = "http://127.0.0.1:$taskSelectedPort"
if ($taskNeedsStart) {
    $taskLog = Join-Path $PSScriptRoot "data\server-$taskSelectedPort.log"
    $taskErrorLog = Join-Path $PSScriptRoot "data\server-$taskSelectedPort-error.log"
    Start-Process -FilePath $taskPythonPath -ArgumentList '-m','uvicorn','backend.app:app','--host','127.0.0.1','--port',"$taskSelectedPort" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput $taskLog -RedirectStandardError $taskErrorLog
    $taskReady = $false
    for ($taskAttempt=0; $taskAttempt -lt 30; $taskAttempt++) {
        try {
            $taskRunning = Invoke-RestMethod "$taskUrl/api/runtime" -TimeoutSec 1
            if ($taskRunning.build_id -eq $taskIdentity.build_id) { $taskReady=$true; break }
        } catch { }
        Start-Sleep -Milliseconds 100
    }
    if (-not $taskReady) { throw "软件服务未就绪，请查看 $taskErrorLog" }
}
if (-not $NoBrowser) { Start-Process $taskUrl }
Write-Output $taskUrl
