param(
    [int]$Port = 0
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING = "utf-8"

function Get-RunningModviiPort {
    $Process = Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -like "*uvicorn*app.main:app*" } |
        Select-Object -First 1
    if (-not $Process) {
        throw "No running MODVII uvicorn server found. Start the server or run the soak verifier first."
    }
    if ($Process.CommandLine -notmatch "--port\s+(\d+)") {
        throw "Could not parse server port from: $($Process.CommandLine)"
    }
    return [int]$Matches[1]
}

if ($Port -le 0) {
    $Port = Get-RunningModviiPort
}

$Uv = Resolve-Uv
$Python = Resolve-Python
if (-not $Uv -and -not $Python) {
    throw "Python 3.11+ or uv is required for dialogue simulation."
}

$ClientScript = Join-Path $env:TEMP "modvii_dialogue_$([guid]::NewGuid().ToString('N')).py"

@"
import asyncio
import json
import time
import urllib.request

import websockets

PORT = $Port
BASE = f"http://127.0.0.1:{PORT}"
QUESTIONS = [
    "\u5c0f\u4e03\uff0c\u4f60\u73b0\u5728\u80fd\u5e2e\u6211\u505a\u4ec0\u4e48\uff1f",
    "\u5c0f\u4e03\uff0c\u89e3\u91ca\u4e00\u4e0b\u4f4e\u5e27\u5c4f\u5e55\u6355\u6349\u548c\u8fde\u7eed\u89c6\u9891\u6a21\u5f0f\u7684\u533a\u522b\u3002",
    "\u5c0f\u4e03\uff0c\u5982\u679c\u6211\u7684\u9ea6\u514b\u98ce\u8d28\u91cf\u5f88\u5dee\uff0c\u4f60\u4f1a\u600e\u4e48\u5904\u7406\uff1f",
]

def post_json(path, payload):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))

def evt(kind, session_id, payload):
    return {
        "id": f"manual_{time.time_ns()}",
        "type": kind,
        "session_id": session_id,
        "ts": int(time.time() * 1000),
        "payload": payload,
    }

async def drain(ws, seconds=5):
    deadline = time.monotonic() + seconds
    finals = []
    events = []
    while time.monotonic() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=0.4)
        except asyncio.TimeoutError:
            continue
        message = json.loads(raw)
        kind = message.get("type", "unknown")
        payload = message.get("payload") or {}
        events.append(kind)
        if kind == "assistant.text.final":
            finals.append(payload.get("text", ""))
        if kind == "error":
            print("ERROR:", json.dumps(payload, ensure_ascii=False))
    return events, finals

async def main():
    session = post_json("/api/session", {})
    session_id = session["session_id"]
    print("SESSION", session_id)
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/session/{session_id}", max_size=8_000_000) as ws:
        events, _finals = await drain(ws, 1)
        print("READY_EVENTS", ",".join(events))
        for text in QUESTIONS:
            print("")
            print("USER", text)
            await ws.send(json.dumps(evt("client.wake.detected", session_id, {"wake_word": "\u5c0f\u4e03"}), ensure_ascii=False))
            await ws.send(json.dumps(evt("client.user.text", session_id, {"text": text}), ensure_ascii=False))
            events, finals = await drain(ws, 6)
            print("EVENTS", ",".join(events))
            if not finals:
                print("MODVII", "<no final answer received>")
            for answer in finals:
                print("MODVII", answer)

asyncio.run(main())
"@ | Set-Content -Path $ClientScript -Encoding ASCII

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
    Remove-Item -Path $ClientScript -Force -ErrorAction SilentlyContinue
}
