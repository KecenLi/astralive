param(
    [string]$ModelSource,
    [string]$OutputDir = "apps\web\public\live2d"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Target = Join-Path $Root $OutputDir
New-Item -ItemType Directory -Force -Path $Target | Out-Null

if (-not $ModelSource) {
    Write-Host "No Live2D model was downloaded."
    Write-Host "Place a licensed Live2D model under $OutputDir and set VITE_LIVE2D_MODEL_URL in .env."
    Write-Host "Do not add sample models unless their license terms have been accepted and recorded locally."
    exit 0
}

Write-Host "ModelSource was provided, but automatic download is intentionally disabled."
Write-Host "Download licensed Live2D assets manually, record the license locally, then place them under $OutputDir."

