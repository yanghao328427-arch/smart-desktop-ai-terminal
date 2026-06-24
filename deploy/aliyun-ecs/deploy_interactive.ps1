[CmdletBinding()]
param(
    [string]$Server = "8.163.38.158",
    [string]$User = "root"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$DistDirectory = Join-Path $ProjectRoot "dist"
$Archive = Join-Path $DistDirectory "smartdesk-ecs-release.tar.gz"
$Installer = Join-Path $PSScriptRoot "install_release.sh"

New-Item -ItemType Directory -Force -Path $DistDirectory | Out-Null
if (Test-Path $Archive) {
    Remove-Item -LiteralPath $Archive -Force
}

Write-Host "[local] Building a secret-free release package..."
Push-Location $ProjectRoot
try {
    & tar.exe -czf $Archive `
        --exclude="backend/.env" `
        --exclude="backend/data" `
        --exclude="backend/app/__pycache__" `
        backend/app backend/requirements.txt
    if ($LASTEXITCODE -ne 0) {
        throw "tar failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

Write-Host "[upload] You will be asked for the ECS root password."
& scp.exe -o ServerAliveInterval=30 $Archive $Installer "${User}@${Server}:/tmp/"
if ($LASTEXITCODE -ne 0) {
    throw "SCP upload failed."
}

Write-Host "[deploy] You may be asked for the password again."
& ssh.exe -o ServerAliveInterval=30 "${User}@${Server}" `
    "bash /tmp/install_release.sh /tmp/smartdesk-ecs-release.tar.gz"
if ($LASTEXITCODE -ne 0) {
    throw "Remote deployment failed. Read the error above; the previous service backup was preserved."
}

Write-Host "[verify] Public HTTP health check..."
$health = Invoke-RestMethod "http://${Server}/api/health" -TimeoutSec 20
$health | ConvertTo-Json -Depth 5
Write-Host "Deployment finished. Keep this window open and return to Codex."
