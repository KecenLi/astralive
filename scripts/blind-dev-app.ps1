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
$WebCommand = @"
. '$CommonLiteral'
Add-ProcessPathEntry -Path (Join-Path `$env:ProgramFiles 'nodejs')
`$WebDir = Join-Path '$RootLiteral' 'apps\web'
Set-Location `$WebDir
Invoke-NodePackageScript -PackagePrefix 'vite' -RelativeScriptPath 'node_modules\vite\bin\vite.js' -Arguments @('--host', '127.0.0.1', '--port', '5173')
"@
$DesktopCommand = @"
. '$CommonLiteral'
`$env:MODVII_RENDERER_URL='http://127.0.0.1:5173'
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
Add-ProcessPathEntry -Path (Join-Path `$env:ProgramFiles 'nodejs')
`$DesktopDir = Join-Path '$RootLiteral' 'apps\desktop'
Set-Location `$DesktopDir
Invoke-NodePackageScript -PackagePrefix 'typescript' -RelativeScriptPath 'node_modules\typescript\bin\tsc' -Arguments @('-p', 'tsconfig.json')
`$ElectronPathFile = Resolve-PnpmPackageScript -PackagePrefix 'electron' -RelativeScriptPath 'node_modules\electron\path.txt'
`$ElectronRoot = Split-Path -Parent `$ElectronPathFile
`$ElectronExe = Join-Path (Join-Path `$ElectronRoot 'dist') ((Get-Content `$ElectronPathFile -Raw).Trim())
Invoke-CmdExecutable -Executable `$ElectronExe -Arguments @('.')
"@
Set-Location $Root

function Test-ViteReady {
    try {
        return (Invoke-WebRequest "http://127.0.0.1:5173" -TimeoutSec 2 -UseBasicParsing).StatusCode -eq 200
    } catch {
        return $false
    }
}

# 1) Web dev server (Vite).
if (Test-ViteReady) {
    Write-Host "Vite already ready on http://127.0.0.1:5173." -ForegroundColor Green
} else {
    Start-Process powershell -ArgumentList @(
        "-NoProfile", "-NoExit", "-ExecutionPolicy", "Bypass", "-Command",
        $WebCommand
    ) -WorkingDirectory $Root
}

Write-Host "Waiting for Vite on http://127.0.0.1:5173 ..." -ForegroundColor Yellow
$ready = $false
foreach ($i in 1..40) {
    if (Test-ViteReady) {
        $ready = $true; break
    }
    Start-Sleep -Seconds 2
}
if ($ready) { Write-Host "Vite ready." -ForegroundColor Green }
else { Write-Host "Vite slow to start; check its window, then continue." -ForegroundColor Red }

# 2) Electron desktop app, loading the dev web URL. It launches its own backend
#    from source (random free port) and waits for its /health.
$env:MODVII_RENDERER_URL = "http://127.0.0.1:5173"
Start-Process powershell -ArgumentList @(
    "-NoProfile", "-NoExit", "-ExecutionPolicy", "Bypass", "-Command",
    $DesktopCommand
) -WorkingDirectory $Root

Write-Host "Launched. The Electron window will appear once its backend reports healthy (model load ~30-60s)." -ForegroundColor Green
