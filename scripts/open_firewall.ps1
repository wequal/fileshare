# Run as Administrator. Opens inbound TCP for Home Fileshare.
param(
    [int]$Port = 8443,
    [string]$RuleName = "Home Fileshare"
)

$existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Rule '$RuleName' already exists."
    exit 0
}

New-NetFirewallRule -DisplayName $RuleName `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort $Port `
    -Action Allow `
    -Profile Private, Domain

Write-Host "Allowed inbound TCP $Port for profiles Private and Domain."
