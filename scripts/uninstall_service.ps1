# Remove the Home Fileshare Scheduled Task created by install_service.ps1.
# Run from an elevated (Administrator) PowerShell.
param()

$ErrorActionPreference = "Stop"
$taskName = "HomeFileshare"

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Scheduled task '$taskName' removed."
} else {
    Write-Host "No scheduled task named '$taskName' found."
}
