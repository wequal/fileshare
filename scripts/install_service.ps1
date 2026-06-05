# Install Home Fileshare as a Windows service using NSSM.
# Download NSSM from https://nssm.cc/ and add nssm.exe to PATH, or set $NssmPath below.
param(
    [string]$NssmPath = "nssm",
    [string]$InstallDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$venvPython = Join-Path $InstallDir "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Error "venv not found. Run run_server.bat once to create venv and install deps."
    exit 1
}

$serviceName = "HomeFileshare"
$uvicornArgs = "-m uvicorn server.main:app --host 0.0.0.0 --port 8443"

& $NssmPath install $serviceName $venvPython $uvicornArgs.Split(" ")
& $NssmPath set $serviceName AppDirectory $InstallDir
& $NssmPath set $serviceName DisplayName "Home Fileshare"
& $NssmPath set $serviceName Description "LAN photo/video file server"
& $NssmPath set $serviceName Start SERVICE_AUTO_START

Write-Host "Service '$serviceName' installed. Start with: nssm start $serviceName"
Write-Host "Ensure config.yaml exists in $InstallDir and run scripts\open_firewall.ps1 as Admin."
