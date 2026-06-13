param(
    [int]$DurationMinutes = 30,
    [switch]$SkipDependencySync
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")
$LogDir = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Get-FreeTcpPort {
    $Listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $Listener.Start()
    try {
        return $Listener.LocalEndpoint.Port
    } finally {
        $Listener.Stop()
    }
}

function Set-ProcessEnv {
    param([hashtable]$Values)
    $Previous = @{}
    foreach ($Name in $Values.Keys) {
        $Previous[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
        [Environment]::SetEnvironmentVariable($Name, [string]$Values[$Name], "Process")
    }
    return $Previous
}

function Restore-ProcessEnv {
    param([hashtable]$Previous)
    foreach ($Name in $Previous.Keys) {
        [Environment]::SetEnvironmentVariable($Name, $Previous[$Name], "Process")
    }
}

function Stop-ProcessTree {
    param([System.Diagnostics.Process]$Process)

    if (-not $Process -or $Process.HasExited) {
        return
    }

    if ($IsWindows -or $env:OS -eq "Windows_NT") {
        Start-Process -FilePath "taskkill.exe" `
            -ArgumentList @("/PID", "$($Process.Id)", "/T", "/F") `
            -WindowStyle Hidden `
            -Wait
        return
    }

    Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
}

$Port = Get-FreeTcpPort
$Uv = Resolve-Uv
$Python = Resolve-Python
if (-not $Uv -and -not $Python) {
    throw "Python 3.11+ or uv is required for MODVII soak verification."
}

if ($Uv -and -not $SkipDependencySync) {
    Push-Location (Join-Path $Root "apps\server")
    try {
        Invoke-CmdExecutable -Executable $Uv -Arguments @("sync", "--group", "dev")
    } finally {
        Pop-Location
    }
}

$ServerOut = Join-Path $LogDir "modvii-soak-server-$((Get-Date).ToString('yyyyMMdd-HHmmss')).out.log"
$ServerErr = Join-Path $LogDir "modvii-soak-server-$((Get-Date).ToString('yyyyMMdd-HHmmss')).err.log"
$ClientScript = Join-Path $env:TEMP "modvii_soak_$([guid]::NewGuid().ToString('N')).py"

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
    DATA_DIR = (Join-Path $Root "data")
}

$PreviousEnv = Set-ProcessEnv -Values $EnvPatch
$Server = $null
try {
    Push-Location (Join-Path $Root "apps\server")
    try {
        if ($Uv) {
            $Server = Start-Process -FilePath $Uv `
                -ArgumentList @("run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port") `
                -WorkingDirectory (Join-Path $Root "apps\server") `
                -RedirectStandardOutput $ServerOut `
                -RedirectStandardError $ServerErr `
                -PassThru
        } else {
            $Server = Start-Process -FilePath $Python `
                -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port") `
                -WorkingDirectory (Join-Path $Root "apps\server") `
                -RedirectStandardOutput $ServerOut `
                -RedirectStandardError $ServerErr `
                -PassThru
        }
    } finally {
        Pop-Location
    }
} finally {
    Restore-ProcessEnv -Previous $PreviousEnv
}

@"
import asyncio
import base64
import json
import time
import urllib.request

import websockets

BASE = "http://127.0.0.1:$Port"
DURATION_SECONDS = $($DurationMinutes * 60)
ONE_BY_ONE_JPEG = "/9j/4AAQSkZJRgABAQAAAQABAAD/2w=="

def post_json(url, payload):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))

def get_json(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))

def event(kind, session_id, payload):
    return {
        "id": f"evt_{time.time_ns()}",
        "type": kind,
        "session_id": session_id,
        "ts": int(time.time() * 1000),
        "payload": payload,
    }

async def drain(ws, stats, seconds=1.5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=0.3)
        except asyncio.TimeoutError:
            continue
        message = json.loads(raw)
        kind = message.get("type", "unknown")
        stats["events"][kind] = stats["events"].get(kind, 0) + 1
        if kind == "error":
            stats["errors"].append(message.get("payload"))

async def main():
    started = time.monotonic()
    while True:
        try:
            health = get_json(f"{BASE}/health")
            if health.get("ok"):
                break
        except Exception:
            pass
        if time.monotonic() - started > 30:
            raise RuntimeError("server health timeout")
        await asyncio.sleep(0.5)

    session = post_json(f"{BASE}/api/session", {})
    session_id = session["session_id"]
    stats = {"duration_seconds": DURATION_SECONDS, "iterations": 0, "events": {}, "errors": []}
    async with websockets.connect(f"ws://127.0.0.1:$Port/ws/session/{session_id}", max_size=8_000_000) as ws:
        await drain(ws, stats, 1.0)
        end_at = time.monotonic() + DURATION_SECONDS
        while time.monotonic() < end_at:
            stats["iterations"] += 1
            await ws.send(json.dumps(event("client.debug.ping", session_id, {})))
            await ws.send(json.dumps(event("client.wake.detected", session_id, {"wake_word": "\u5c0f\u4e03"})))
            await ws.send(json.dumps(event("client.user.text", session_id, {"text": "\u5c0f\u4e03\uff0c\u7b80\u77ed\u8bf4\u660e\u4f60\u73b0\u5728\u80fd\u505a\u4ec0\u4e48\u3002"})))
            await ws.send(json.dumps(event("client.media.frame", session_id, {
                "frame_id": f"soak_{stats['iterations']}",
                "mime": "image/jpeg",
                "width": 1,
                "height": 1,
                "quality": 0.72,
                "capture_reason": "screen_low_fps",
                "scene_hash": f"hash_{stats['iterations']}",
                "data_base64": ONE_BY_ONE_JPEG,
                "prompt": "soak test frame",
            })))
            await drain(ws, stats, 2.0)
            await asyncio.sleep(3.0)

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if stats["errors"]:
        raise SystemExit(2)

asyncio.run(main())
"@ | Set-Content -Path $ClientScript -Encoding UTF8

try {
    Push-Location (Join-Path $Root "apps\server")
    try {
        if ($Uv) {
            Invoke-CmdExecutable -Executable $Uv -Arguments @("run", "python", $ClientScript)
        } else {
            Invoke-CmdExecutable -Executable $Python -Arguments @($ClientScript)
        }
    } finally {
        Pop-Location
    }
} finally {
    Stop-ProcessTree -Process $Server
    Remove-Item -Path $ClientScript -Force -ErrorAction SilentlyContinue
}

Write-Host "MODVII soak verification completed for $DurationMinutes minute(s)."
Write-Host "Server logs: $ServerOut / $ServerErr"
