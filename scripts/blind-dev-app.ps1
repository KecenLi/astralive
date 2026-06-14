# Launch the MODVII dev app (Vite web + Electron desktop) from source, so it
# runs with the latest fixes (CosyVoice OOM-survive + retry, GPU ASR/TTS
# stagger, dialogue watchdog). In dev mode the desktop app starts its OWN
# backend from source on a free port, so no separate backend is needed.
#
# Run from a shell where Node.js/Corepack is available:
#   powershell -ExecutionPolicy Bypass -File scripts\blind-dev-app.ps1
#
# Two windows appear: the Vite web dev server and the Electron desktop app.
# Grant camera / microphone / screen permissions when prompted.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Common = Join-Path $PSScriptRoot "common.ps1"
$RootLiteral = $Root.Replace("'", "''")
$CommonLiteral = $Common.Replace("'", "''")
Set-Location $Root

# 1) Web dev server (Vite).
Start-Process powershell -ArgumentList @(
    "-NoProfile", "-NoExit", "-ExecutionPolicy", "Bypass", "-Command",
    ". '$CommonLiteral'; Set-Location '$RootLiteral'; Invoke-Pnpm @('--filter', '@modvii/web', 'dev')"
) -WorkingDirectory $Root

Write-Host "Waiting for Vite on http://127.0.0.1:5173 ..." -ForegroundColor Yellow
$ready = $false
foreach ($i in 1..40) {
    try {
        if ((Invoke-WebRequest "http://127.0.0.1:5173" -TimeoutSec 2 -UseBasicParsing).StatusCode -eq 200) {
            $ready = $true; break
        }
    } catch { Start-Sleep -Seconds 2 }
}
if ($ready) { Write-Host "Vite ready." -ForegroundColor Green }
else { Write-Host "Vite slow to start; check its window, then continue." -ForegroundColor Red }

# 2) Electron desktop app, loading the dev web URL. It launches its own backend
#    from source (random free port) and waits for its /health.
$env:MODVII_RENDERER_URL = "http://127.0.0.1:5173"
Start-Process powershell -ArgumentList @(
    "-NoProfile", "-NoExit", "-ExecutionPolicy", "Bypass", "-Command",
    ". '$CommonLiteral'; `$env:MODVII_RENDERER_URL='http://127.0.0.1:5173'; Set-Location '$RootLiteral'; Invoke-Pnpm @('--filter', 'modvii-desktop', 'dev')"
) -WorkingDirectory $Root

Write-Host "Launched. The Electron window will appear once its backend reports healthy (model load ~30-60s)." -ForegroundColor Green
