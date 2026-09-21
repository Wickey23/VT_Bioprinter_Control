$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Target = Join-Path $Root "Marlin-upstream"

if (Test-Path $Target) {
    Write-Host "Marlin-upstream already exists. Updating..."
    git -C $Target pull --ff-only
} else {
    Write-Host "Cloning official Marlin 2.1.x..."
    git clone --depth 1 --branch 2.1.x https://github.com/MarlinFirmware/Marlin.git $Target
}

Write-Host ""
Write-Host "Marlin source ready at: $Target"
Write-Host "DO NOT FLASH until HARDWARE_PROFILE.md is verified."
