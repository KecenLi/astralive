param(
    [int]$ServerPort = 18765,
    [int]$WebPort = 15173,
    [switch]$SkipDependencySync,
    [switch]$Headed,
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")

function Get-FreeTcpPort {
    $Listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $Listener.Start()
    try {
        return $Listener.LocalEndpoint.Port
    } finally {
        $Listener.Stop()
    }
}

function Test-TcpPortOpen {
    param([int]$Port)

    $Client = [System.Net.Sockets.TcpClient]::new()
    try {
        $Task = $Client.ConnectAsync("127.0.0.1", $Port)
        return $Task.Wait(200)
    } catch {
        return $false
    } finally {
        $Client.Dispose()
    }
}

function Resolve-Chrome {
    $Candidates = @(
        (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"),
        (Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe")
    )

    foreach ($Candidate in $Candidates) {
        if ($Candidate -and (Test-Path $Candidate)) {
            return $Candidate
        }
    }
    throw "Chrome or Edge was not found in the standard install paths."
}

function Resolve-PnpmPackageScript {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PackagePrefix,
        [Parameter(Mandatory = $true)]
        [string]$RelativeScriptPath
    )

    $PnpmRoot = Join-Path $Root "node_modules\.pnpm"
    $Script = Get-ChildItem -Path $PnpmRoot -Directory -Filter "$PackagePrefix@*" |
        Sort-Object -Property Name -Descending |
        ForEach-Object { Join-Path $_.FullName $RelativeScriptPath } |
        Where-Object { Test-Path $_ } |
        Select-Object -First 1

    if (-not $Script) {
        throw "Could not find $PackagePrefix script at $RelativeScriptPath. Run pnpm install first."
    }
    return $Script
}

function Invoke-WithTemporaryEnv {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Action,
        [hashtable]$Environment = @{}
    )

    $Previous = @{}
    foreach ($Name in $Environment.Keys) {
        $Previous[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
        [Environment]::SetEnvironmentVariable($Name, [string]$Environment[$Name], "Process")
    }

    try {
        & $Action
    } finally {
        foreach ($Name in $Environment.Keys) {
            [Environment]::SetEnvironmentVariable($Name, $Previous[$Name], "Process")
        }
    }
}

function Start-ProcessWithEnv {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [string[]]$Arguments = @(),
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,
        [hashtable]$Environment = @{},
        [Parameter(Mandatory = $true)]
        [string]$StdOut,
        [Parameter(Mandatory = $true)]
        [string]$StdErr
    )

    return Invoke-WithTemporaryEnv -Environment $Environment -Action {
        $ArgumentLine = (@($Arguments) | ForEach-Object { ConvertTo-CmdArgument $_ }) -join " "
        Start-Process -FilePath $Executable `
            -ArgumentList $ArgumentLine `
            -WorkingDirectory $WorkingDirectory `
            -RedirectStandardOutput $StdOut `
            -RedirectStandardError $StdErr `
            -PassThru
    }
}

function Get-LogTail {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return ""
    }
    return (Get-Content -Path $Path -Tail 80 -ErrorAction SilentlyContinue) -join "`n"
}

function Wait-HttpOk {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [int]$TimeoutSeconds = 30,
        [System.Diagnostics.Process]$Process,
        [string]$StdOut = "",
        [string]$StdErr = "",
        [string]$Label = "HTTP endpoint"
    )

    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $Deadline) {
        if ($Process -and $Process.HasExited) {
            $Out = Get-LogTail -Path $StdOut
            $Err = Get-LogTail -Path $StdErr
            throw "$Label process exited early with code $($Process.ExitCode).`nstdout:`n$Out`nstderr:`n$Err"
        }

        try {
            $Response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
            if ($Response.StatusCode -ge 200 -and $Response.StatusCode -lt 400) {
                return
            }
        } catch {
            Start-Sleep -Milliseconds 300
        }
    }

    $Out = Get-LogTail -Path $StdOut
    $Err = Get-LogTail -Path $StdErr
    throw "Timed out waiting for $Label at $Url.`nstdout:`n$Out`nstderr:`n$Err"
}

function Stop-ManagedProcess {
    param([System.Diagnostics.Process]$Process)

    if ($Process -and -not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        try {
            $Process.WaitForExit(5000) | Out-Null
        } catch {
            # Ignore cleanup races.
        }
    }
}

if (Test-TcpPortOpen -Port $ServerPort) {
    $ServerPort = Get-FreeTcpPort
}
if (Test-TcpPortOpen -Port $WebPort) {
    $WebPort = Get-FreeTcpPort
}

$WorkDir = Join-Path $env:TEMP "astralive_browser_mic_offline_$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null
$FakeAudioPath = Join-Path $WorkDir "fake_microphone.wav"
$ChromeProfile = Join-Path $WorkDir "chrome-profile"
$GenerateAudioScript = Join-Path $WorkDir "generate_fake_microphone_audio.py"
$CdpScript = Join-Path $WorkDir "verify_browser_realtime_mic_offline.js"
$ServerOut = Join-Path $WorkDir "server.stdout.log"
$ServerErr = Join-Path $WorkDir "server.stderr.log"
$WebOut = Join-Path $WorkDir "web.stdout.log"
$WebErr = Join-Path $WorkDir "web.stderr.log"

$GenerateAudio = @'
import math
import struct
import sys
import wave
from pathlib import Path

output = Path(__OUTPUT_JSON__)
sample_rate = 48000
duration_seconds = 8
amplitude = 0.32

frames = bytearray()
for index in range(sample_rate * duration_seconds):
    t = index / sample_rate
    envelope = min(1.0, t / 0.35, (duration_seconds - t) / 0.35)
    value = (
        math.sin(2 * math.pi * 220 * t) * 0.55
        + math.sin(2 * math.pi * 440 * t) * 0.30
        + math.sin(2 * math.pi * 660 * t) * 0.15
    )
    sample = int(max(-1.0, min(1.0, value * amplitude * envelope)) * 32767)
    frames.extend(struct.pack("<h", sample))

output.parent.mkdir(parents=True, exist_ok=True)
with wave.open(str(output), "wb") as wav:
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(sample_rate)
    wav.writeframes(bytes(frames))

print(f"fake_audio_path={output}")
print(f"sample_rate={sample_rate}")
print(f"duration_seconds={duration_seconds}")
print(f"pcm_bytes={len(frames)}")
'@
$GenerateAudio = $GenerateAudio.Replace("__OUTPUT_JSON__", ($FakeAudioPath | ConvertTo-Json -Compress))
Set-Content -Path $GenerateAudioScript -Value $GenerateAudio -Encoding UTF8

$ServerPython = Join-Path $Root "apps\server\.venv\Scripts\python.exe"
if (-not (Test-Path $ServerPython)) {
    $Uv = Resolve-Uv
    if ($Uv -and -not $SkipDependencySync) {
        Push-Location (Join-Path $Root "apps\server")
        try {
            Invoke-CmdExecutable -Executable $Uv -Arguments @("sync")
        } finally {
            Pop-Location
        }
    }
}
if (-not (Test-Path $ServerPython)) {
    $ServerPython = Resolve-Python
}
if (-not $ServerPython) {
    throw "Python 3.11+ is required to generate fake microphone audio and start the mock backend."
}

$Node = Resolve-CommandPath -Name "node.exe" -Candidates @(
    (Join-Path $env:ProgramFiles "nodejs\node.exe")
)
if (-not $Node) {
    throw "Node.js is required for browser realtime microphone verification."
}
$ViteScript = Resolve-PnpmPackageScript -PackagePrefix "vite" -RelativeScriptPath "node_modules\vite\bin\vite.js"
$Chrome = Resolve-Chrome

$ServerProcess = $null
$WebProcess = $null
$ChromeProcess = $null
try {
    Invoke-CmdExecutable -Executable $ServerPython -Arguments @($GenerateAudioScript)

    $ServerEnv = @{
        "SERVER_HOST" = "127.0.0.1"
        "SERVER_PORT" = "$ServerPort"
        "WEB_ORIGIN" = "http://127.0.0.1:$WebPort"
        "ASR_PROVIDER" = "mock"
        "VISION_PROVIDER" = "mock"
        "LLM_PROVIDER" = "mock"
        "TTS_PROVIDER" = "mock"
        "REALTIME_PROVIDER" = "mock"
        "DATA_DIR" = (Join-Path $WorkDir "data")
    }
    $ServerProcess = Start-ProcessWithEnv `
        -Executable $ServerPython `
        -Arguments @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$ServerPort") `
        -WorkingDirectory (Join-Path $Root "apps\server") `
        -Environment $ServerEnv `
        -StdOut $ServerOut `
        -StdErr $ServerErr

    $ServerBaseUrl = "http://127.0.0.1:$ServerPort"
    Wait-HttpOk -Url "$ServerBaseUrl/health" -TimeoutSeconds 45 -Process $ServerProcess -StdOut $ServerOut -StdErr $ServerErr -Label "mock backend"

    $WebUrl = "http://127.0.0.1:$WebPort"
    $WebEnv = @{
        "VITE_API_BASE_URL" = $ServerBaseUrl
        "VITE_LIVE2D_MODEL_URL" = ""
    }
    $WebProcess = Start-ProcessWithEnv `
        -Executable $Node `
        -Arguments @($ViteScript, "--host", "127.0.0.1", "--port", "$WebPort") `
        -WorkingDirectory (Join-Path $Root "apps\web") `
        -Environment $WebEnv `
        -StdOut $WebOut `
        -StdErr $WebErr

    Wait-HttpOk -Url $WebUrl -TimeoutSeconds 45 -Process $WebProcess -StdOut $WebOut -StdErr $WebErr -Label "mock web"

    $RemoteDebuggingPort = Get-FreeTcpPort
    $ChromeArgs = @(
        "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=$RemoteDebuggingPort",
        "--user-data-dir=$ChromeProfile",
        "--no-first-run",
        "--no-default-browser-check",
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
        "--use-file-for-fake-audio-capture=$FakeAudioPath",
        "--autoplay-policy=no-user-gesture-required",
        "--mute-audio",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-features=CalculateNativeWinOcclusion",
        $WebUrl
    )
    if (-not $Headed) {
        $ChromeArgs = @("--headless=new", "--disable-gpu") + $ChromeArgs
    }

    $NodeVerifier = @'
const { setTimeout: sleep } = require("node:timers/promises");

const DEBUG_PORT = Number(__DEBUG_PORT_JSON__);
const WEB_URL = __WEB_URL_JSON__;
const TARGET_TIMEOUT_MS = 20000;
const VERIFY_TIMEOUT_MS = 45000;

function parseEventPayload(payloadData) {
  try {
    const parsed = JSON.parse(payloadData);
    if (parsed && typeof parsed.type === "string") return parsed;
  } catch {
    return null;
  }
  return null;
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}`);
  return response.json();
}

async function waitFor(fn, timeoutMs, label, intervalMs = 250) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      const value = await fn();
      if (value) return value;
    } catch (error) {
      lastError = error;
    }
    await sleep(intervalMs);
  }
  throw new Error(`Timed out waiting for ${label}${lastError ? `: ${lastError.message}` : ""}`);
}

class CdpClient {
  constructor(webSocketUrl) {
    this.webSocketUrl = webSocketUrl;
    this.nextId = 1;
    this.pending = new Map();
    this.handlers = new Map();
  }

  async connect() {
    if (typeof WebSocket === "undefined") {
      throw new Error("Node global WebSocket is not available. Use Node.js 22+.");
    }
    this.socket = new WebSocket(this.webSocketUrl);
    this.socket.addEventListener("message", (message) => this.handleMessage(message.data));
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("CDP websocket open timed out")), 10000);
      this.socket.addEventListener("open", () => {
        clearTimeout(timer);
        resolve();
      }, { once: true });
      this.socket.addEventListener("error", () => {
        clearTimeout(timer);
        reject(new Error("CDP websocket failed to open"));
      }, { once: true });
    });
  }

  handleMessage(raw) {
    const message = JSON.parse(raw);
    if (message.id && this.pending.has(message.id)) {
      const { resolve, reject, timer } = this.pending.get(message.id);
      clearTimeout(timer);
      this.pending.delete(message.id);
      if (message.error) reject(new Error(message.error.message));
      else resolve(message.result);
      return;
    }
    const handlers = this.handlers.get(message.method) || [];
    for (const handler of handlers) handler(message.params || {});
  }

  on(method, handler) {
    const handlers = this.handlers.get(method) || [];
    handlers.push(handler);
    this.handlers.set(method, handlers);
  }

  send(method, params = {}) {
    const id = this.nextId++;
    const payload = JSON.stringify({ id, method, params });
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method} timed out`));
      }, 15000);
      this.pending.set(id, { resolve, reject, timer });
      this.socket.send(payload);
    });
  }

  close() {
    this.socket?.close();
  }
}

async function main() {
  const target = await waitFor(async () => {
    const targets = await getJson(`http://127.0.0.1:${DEBUG_PORT}/json`);
    return targets.find((candidate) =>
      candidate.type === "page" &&
      candidate.url.startsWith(WEB_URL) &&
      candidate.webSocketDebuggerUrl
    );
  }, TARGET_TIMEOUT_MS, "Chrome page target");

  const cdp = new CdpClient(target.webSocketDebuggerUrl);
  await cdp.connect();

  const sentTypes = {};
  const receivedTypes = {};
  let sentAudioChunks = 0;
  let sentFinalChunks = 0;
  let asrText = "";
  let assistantText = "";

  const count = (table, type) => {
    table[type] = (table[type] || 0) + 1;
  };

  cdp.on("Network.webSocketFrameSent", ({ response }) => {
    const event = parseEventPayload(response?.payloadData || "");
    if (!event) return;
    count(sentTypes, event.type);
    if (event.type === "client.media.audio_chunk") {
      if (event.payload?.is_final) sentFinalChunks += 1;
      else sentAudioChunks += 1;
    }
  });

  cdp.on("Network.webSocketFrameReceived", ({ response }) => {
    const event = parseEventPayload(response?.payloadData || "");
    if (!event) return;
    count(receivedTypes, event.type);
    if (event.type === "error") {
      throw new Error(`Server error event: ${JSON.stringify(event.payload)}`);
    }
    if (event.type === "asr.transcript.final") asrText = String(event.payload?.text || "");
    if (event.type === "assistant.text.final") assistantText = String(event.payload?.text || "");
  });

  try {
    await cdp.send("Runtime.enable");
    await cdp.send("Network.enable");
    await cdp.send("Page.enable");

    await waitFor(async () => {
      const result = await cdp.send("Runtime.evaluate", {
        expression: "document.readyState",
        returnByValue: true,
      });
      return result.result?.value === "complete" || result.result?.value === "interactive";
    }, TARGET_TIMEOUT_MS, "document readiness");

    const buttonExpression = `(() => {
      const button = document.querySelector(".mic-panel .toolbar button:nth-of-type(4)");
      if (!button) return { found: false };
      return { found: true, disabled: button.disabled, title: button.title };
    })()`;

    await waitFor(async () => {
      const result = await cdp.send("Runtime.evaluate", {
        expression: buttonExpression,
        returnByValue: true,
      });
      const value = result.result?.value;
      return value?.found && !value.disabled ? value : null;
    }, TARGET_TIMEOUT_MS, "enabled realtime microphone button");

    await cdp.send("Runtime.evaluate", {
      expression: `document.querySelector(".mic-panel .toolbar button:nth-of-type(4)").click()`,
      awaitPromise: true,
    });

    await waitFor(() => sentAudioChunks >= 3, 20000, "browser PCM audio chunks");
    await sleep(3500);

    await cdp.send("Runtime.evaluate", {
      expression: `document.querySelector(".mic-panel .toolbar button:nth-of-type(4)").click()`,
      awaitPromise: true,
    });

    try {
      await waitFor(() =>
        sentFinalChunks >= 1 &&
        receivedTypes["asr.transcript.final"] >= 1 &&
        receivedTypes["assistant.text.final"] >= 1 &&
        receivedTypes["assistant.audio.done"] >= 1,
        VERIFY_TIMEOUT_MS,
        "offline browser realtime microphone response"
      );
    } catch (error) {
      console.error(`sent_audio_chunks=${sentAudioChunks}`);
      console.error(`sent_final_chunks=${sentFinalChunks}`);
      console.error(`sent_types=${JSON.stringify(sentTypes)}`);
      console.error(`received_types=${JSON.stringify(receivedTypes)}`);
      throw error;
    }

    console.log(`web_url=${WEB_URL}`);
    console.log(`sent_audio_chunks=${sentAudioChunks}`);
    console.log(`sent_final_chunks=${sentFinalChunks}`);
    console.log(`asr_text=${asrText.slice(0, 160)}`);
    console.log(`assistant_text=${assistantText.slice(0, 160)}`);
    console.log(`sent_types=${JSON.stringify(sentTypes)}`);
    console.log(`received_types=${JSON.stringify(receivedTypes)}`);
  } finally {
    cdp.close();
  }
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
'@

    $NodeVerifier = $NodeVerifier.Replace("__DEBUG_PORT_JSON__", ($RemoteDebuggingPort | ConvertTo-Json -Compress))
    $NodeVerifier = $NodeVerifier.Replace("__WEB_URL_JSON__", ($WebUrl | ConvertTo-Json -Compress))
    Set-Content -Path $CdpScript -Value $NodeVerifier -Encoding UTF8

    $ChromeProcess = Start-Process -FilePath $Chrome -ArgumentList $ChromeArgs -PassThru
    Start-Sleep -Seconds 2

    Invoke-CmdExecutable -Executable $Node -Arguments @($CdpScript)
} finally {
    Stop-ManagedProcess -Process $ChromeProcess
    Stop-ManagedProcess -Process $WebProcess
    Stop-ManagedProcess -Process $ServerProcess

    if (-not $KeepArtifacts) {
        Remove-Item -Path $WorkDir -Recurse -Force -ErrorAction SilentlyContinue
    } else {
        Write-Host "Browser offline verification artifacts kept at: $WorkDir"
    }
}

Write-Host "Offline browser realtime microphone verification finished."
