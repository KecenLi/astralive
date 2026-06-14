param(
    [switch]$RealApi,
    [switch]$Portable,
    [string]$NoiseProfile = "low_noise",
    [string]$RequestText = "请简短介绍一下你现在能做什么。"
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

if ($RealApi) {
    . (Join-Path $PSScriptRoot "common.ps1")
    Assert-ApiHoldClear -Provider "vertex-ai"
    $Node = Resolve-Node
    if (-not $Node) {
        throw "Node.js is required for desktop real API verification."
    }
    $Python = Resolve-Python
    $Uv = Resolve-Uv
    $Previous = @{}
    $EnvPatch = @{
        MODVII_REAL_API = "1"
        MODVII_NOISE_PROFILE = $NoiseProfile
        MODVII_REQUEST_TEXT = $RequestText
        MODVII_DESKTOP_EXE = $DesktopExe
    }
    if ($Python -and -not $Uv) {
        $EnvPatch["MODVII_PYTHON"] = $Python
    }
    if ($Uv) {
        $EnvPatch["MODVII_UV"] = $Uv
    }
    foreach ($Name in $EnvPatch.Keys) {
        $Previous[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
        [Environment]::SetEnvironmentVariable($Name, [string]$EnvPatch[$Name], "Process")
    }
    try {
        Invoke-ApiCommand `
            -Executable $Node `
            -Arguments @((Join-Path $PSScriptRoot "verify-desktop-interaction.mjs")) `
            -Provider "vertex-ai" `
            -CommandName "Desktop real API verification"
    } finally {
        foreach ($Name in $Previous.Keys) {
            [Environment]::SetEnvironmentVariable($Name, $Previous[$Name], "Process")
        }
    }
    return
}

$ExistingAppPids = @(
    Get-Process -Name "MODVII" -ErrorAction SilentlyContinue |
        ForEach-Object { $_.Id }
)
$ExistingServerPids = @(
    Get-Process -Name "modvii-server" -ErrorAction SilentlyContinue |
        ForEach-Object { $_.Id }
)

$EnvPatch = @{
    ASR_PROVIDER = "mock"
    VISION_PROVIDER = "mock"
    LLM_PROVIDER = "mock"
    TTS_PROVIDER = "mock"
    REALTIME_PROVIDER = "none"
}
$Previous = @{}
foreach ($Name in $EnvPatch.Keys) {
    $Previous[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
    [Environment]::SetEnvironmentVariable($Name, [string]$EnvPatch[$Name], "Process")
}
$PreviousElectronRunAsNode = [Environment]::GetEnvironmentVariable("ELECTRON_RUN_AS_NODE", "Process")
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue

$Started = $null
try {
    $Started = Start-Process -FilePath $DesktopExe -PassThru
    $Ready = $false
    $HealthUrl = ""
    $ServerPid = 0

    for ($Index = 0; $Index -lt 60; $Index++) {
        $ServerProcesses = @(
            Get-Process -Name "modvii-server" -ErrorAction SilentlyContinue |
                Where-Object { $ExistingServerPids -notcontains $_.Id }
        )

        foreach ($ServerProcess in $ServerProcesses) {
            $Connections = @(
                Get-NetTCPConnection -State Listen -OwningProcess $ServerProcess.Id -ErrorAction SilentlyContinue |
                    Where-Object { $_.LocalAddress -eq "127.0.0.1" }
            )
            foreach ($Connection in $Connections) {
                $Candidate = "http://127.0.0.1:$($Connection.LocalPort)/health"
                try {
                    $Response = Invoke-RestMethod -Uri $Candidate -TimeoutSec 2
                    if ($Response.ok) {
                        $Ready = $true
                        $HealthUrl = $Candidate
                        $ServerPid = $ServerProcess.Id
                        break
                    }
                } catch {
                    # Keep polling until the backend is ready.
                }
            }
            if ($Ready) {
                break
            }
        }

        if ($Ready) {
            break
        }
        Start-Sleep -Milliseconds 500
    }

    if (-not $Ready) {
        throw "Desktop app did not expose a healthy backend within 30 seconds."
    }

    Write-Host "Desktop smoke ok. app_pid=$($Started.Id) server_pid=$ServerPid health=$HealthUrl"
} finally {
    $NewServerPids = @(
        Get-Process -Name "modvii-server" -ErrorAction SilentlyContinue |
            Where-Object { $ExistingServerPids -notcontains $_.Id } |
            ForEach-Object { $_.Id }
    )
    $NewAppPids = @(
        Get-Process -Name "MODVII" -ErrorAction SilentlyContinue |
            Where-Object { $ExistingAppPids -notcontains $_.Id } |
            ForEach-Object { $_.Id }
    )

    foreach ($ProcessId in @($NewServerPids + $NewAppPids)) {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }

    foreach ($Name in $Previous.Keys) {
        [Environment]::SetEnvironmentVariable($Name, $Previous[$Name], "Process")
    }
    [Environment]::SetEnvironmentVariable("ELECTRON_RUN_AS_NODE", $PreviousElectronRunAsNode, "Process")
}
