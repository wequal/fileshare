# Install Home Fileshare as a Windows Scheduled Task that starts at system boot.
# No third-party tools required (this replaces the old NSSM-based approach).
# Run from an elevated (Administrator) PowerShell.
param(
    [int]$Port = 8443,
    [string]$InstallDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"
$taskName = "HomeFileshare"

# Prefer pythonw.exe so the server runs without a console window.
$pythonw = Join-Path $InstallDir "venv\Scripts\pythonw.exe"
$python = Join-Path $InstallDir "venv\Scripts\python.exe"
if (Test-Path $pythonw) {
    $exe = $pythonw
} elseif (Test-Path $python) {
    $exe = $python
} else {
    Write-Error "venv not found. Run run_server.bat once to create the venv and install dependencies."
    exit 1
}

$arguments = "-m uvicorn server.main:app --host 0.0.0.0 --port $Port --timeout-keep-alive 600"

$action = New-ScheduledTaskAction -Execute $exe -Argument $arguments -WorkingDirectory $InstallDir
$trigger = New-ScheduledTaskTrigger -AtStartup
# Run as SYSTEM with highest privileges so it starts at boot without a logged-in user.
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0)

# Replace any existing task with the same name.
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings `
    -Description "LAN photo/video file server" | Out-Null

Start-ScheduledTask -TaskName $taskName

Write-Host "Scheduled task '$taskName' installed and started. It runs at every system boot."
Write-Host "Ensure config.yaml exists in $InstallDir and open the firewall for port $Port."
