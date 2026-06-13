param(
    [switch]$Portable
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$DesktopExe = if ($Portable) {
    Join-Path $Root "dist\desktop\MODVII 0.1.0.exe"
} else {
    Join-Path $Root "dist\desktop\win-unpacked\MODVII.exe"
}
if (-not (Test-Path $DesktopExe)) {
    throw "Desktop exe not found: $DesktopExe"
}

$LogDir = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Variant = if ($Portable) { "portable" } else { "unpacked" }
$ReportPath = Join-Path $LogDir "desktop-renderer-smoke-$Variant-$((Get-Date).ToString('yyyyMMdd-HHmmss')).json"

$PreviousSmokePath = [Environment]::GetEnvironmentVariable("MODVII_RENDERER_SMOKE_PATH", "Process")
$PreviousElectronRunAsNode = [Environment]::GetEnvironmentVariable("ELECTRON_RUN_AS_NODE", "Process")
$PreviousProviders = @{}
foreach ($Name in @("ASR_PROVIDER", "VISION_PROVIDER", "LLM_PROVIDER", "TTS_PROVIDER", "REALTIME_PROVIDER")) {
    $PreviousProviders[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
}

Get-Process -Name "MODVII", "modvii-server" -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue

try {
    [Environment]::SetEnvironmentVariable("MODVII_RENDERER_SMOKE_PATH", $ReportPath, "Process")
    Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
    [Environment]::SetEnvironmentVariable("ASR_PROVIDER", "mock", "Process")
    [Environment]::SetEnvironmentVariable("VISION_PROVIDER", "mock", "Process")
    [Environment]::SetEnvironmentVariable("LLM_PROVIDER", "mock", "Process")
    [Environment]::SetEnvironmentVariable("TTS_PROVIDER", "mock", "Process")
    [Environment]::SetEnvironmentVariable("REALTIME_PROVIDER", "none", "Process")

    $Started = Start-Process -FilePath $DesktopExe -PassThru
    $Ready = $false
    for ($Index = 0; $Index -lt 80; $Index++) {
        if (Test-Path $ReportPath) {
            $Ready = $true
            break
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $Ready) {
        throw "Renderer smoke report was not written. pid=$($Started.Id)"
    }

    $Report = Get-Content -Path $ReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($Report.error) {
        throw "Renderer smoke failed: $($Report.error)"
    }
    if ($Report.rootChildren -lt 1) {
        throw "Renderer root is empty. Report: $ReportPath"
    }
    if (-not $Report.href -or $Report.href -notlike "file://*") {
        throw "Renderer did not load from packaged file URL. Report: $ReportPath"
    }
    if ($Report.stylesheets -lt 1) {
        throw "Renderer CSS did not load. Report: $ReportPath"
    }

    Write-Host "Desktop renderer smoke ok. target=$Variant rootChildren=$($Report.rootChildren) stylesheets=$($Report.stylesheets) report=$ReportPath"
} finally {
    Get-Process -Name "MODVII", "modvii-server" -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    [Environment]::SetEnvironmentVariable("MODVII_RENDERER_SMOKE_PATH", $PreviousSmokePath, "Process")
    [Environment]::SetEnvironmentVariable("ELECTRON_RUN_AS_NODE", $PreviousElectronRunAsNode, "Process")
    foreach ($Name in $PreviousProviders.Keys) {
        [Environment]::SetEnvironmentVariable($Name, $PreviousProviders[$Name], "Process")
    }
}
