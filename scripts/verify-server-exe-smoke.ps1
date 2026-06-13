param(
    [int]$Port = 48761
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$ServerExe = Join-Path $Root "apps\server\dist\modvii-server\modvii-server.exe"
if (-not (Test-Path $ServerExe)) {
    throw "Server exe not found: $ServerExe"
}

$Out = Join-Path $LogDir "server-exe-smoke.out.log"
$Err = Join-Path $LogDir "server-exe-smoke.err.log"

$EnvPatch = @{
    APP_NAME = "MODVII"
    WAKE_WORD = "小七"
    SERVER_HOST = "127.0.0.1"
    SERVER_PORT = "$Port"
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

$Server = $null
try {
    $Server = Start-Process -FilePath $ServerExe `
        -RedirectStandardOutput $Out `
        -RedirectStandardError $Err `
        -PassThru

    $Ready = $false
    for ($Index = 0; $Index -lt 40; $Index++) {
        try {
            $Response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
            if ($Response.ok) {
                $Ready = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }

    if (-not $Ready) {
        throw "Server exe health timeout. Logs: $Out / $Err"
    }

    Write-Host "Server exe health ok. pid=$($Server.Id)"
} finally {
    if ($Server -and -not $Server.HasExited) {
        Stop-Process -Id $Server.Id -Force
    }
    foreach ($Name in $Previous.Keys) {
        [Environment]::SetEnvironmentVariable($Name, $Previous[$Name], "Process")
    }
}
