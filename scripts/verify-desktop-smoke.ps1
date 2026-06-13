$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$DesktopExe = Join-Path $Root "dist\desktop\win-unpacked\MODVII.exe"
if (-not (Test-Path $DesktopExe)) {
    throw "Desktop exe not found: $DesktopExe"
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
