# Create a deployment zip (no venv, no locked DB, no secrets).
param(
    [string]$OutZip = (Join-Path (Split-Path $PSScriptRoot -Parent) "fileshare-deploy.zip")
)

$root = Split-Path $PSScriptRoot -Parent
$temp = Join-Path $env:TEMP ("fileshare-deploy-" + [guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Path $temp | Out-Null

$excludeDirs = @("venv", "data", "__pycache__", ".git")
$excludeFiles = @("config.yaml", "*.db", "*.db-journal", "fileshare-deploy.zip")

Get-ChildItem -Path $root -Force | Where-Object {
    $name = $_.Name
    if ($name -in $excludeDirs) { return $false }
    if ($name -like "*.db") { return $false }
    if ($name -eq "config.yaml") { return $false }
    if ($name -eq "fileshare-deploy.zip") { return $false }
    return $true
} | Copy-Item -Destination $temp -Recurse -Force

if (Test-Path $OutZip) { Remove-Item $OutZip -Force }
Compress-Archive -Path (Join-Path $temp "*") -DestinationPath $OutZip -Force
Remove-Item $temp -Recurse -Force

Write-Host "Created: $OutZip"
Write-Host "Copy to new PC, then: copy config.example.yaml config.yaml && run_server.bat"
