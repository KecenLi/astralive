$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

Push-Location $Root
try {
    if (-not (Test-Path ".env")) {
        Copy-Item ".env.example" ".env"
    }
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "dev.ps1") all
} finally {
    Pop-Location
}

