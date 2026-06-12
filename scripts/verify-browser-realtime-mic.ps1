param(
    [string]$WebUrl = "http://127.0.0.1:5173",
    [string]$ServerBaseUrl = "http://127.0.0.1:8765",
    [string]$Text = "AstraLive browser microphone verification. Please answer briefly in Chinese.",
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

$Health = Invoke-WebRequest -UseBasicParsing -Uri "$($ServerBaseUrl.TrimEnd('/'))/health" -TimeoutSec 5
if ($Health.StatusCode -ne 200) {
    throw "Backend health check failed with HTTP $($Health.StatusCode)."
}

$Page = Invoke-WebRequest -UseBasicParsing -Uri $WebUrl -TimeoutSec 5
if ($Page.StatusCode -ne 200) {
    throw "Web page check failed with HTTP $($Page.StatusCode)."
}

$WorkDir = Join-Path $env:TEMP "astralive_browser_mic_$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null
$FakeAudioPath = Join-Path $WorkDir "fake_microphone.wav"
$ChromeProfile = Join-Path $WorkDir "chrome-profile"
$GenerateAudioScript = Join-Path $WorkDir "generate_fake_microphone_audio.py"
$CdpScript = Join-Path $WorkDir "verify_browser_realtime_mic.js"

$GenerateAudio = @'
import asyncio
import base64
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from app.config import get_settings
from app.contracts.model_io import TTSInput
from app.providers.registry import ProviderRegistry

OUTPUT = Path(__OUTPUT_JSON__)
TEXT = __TEXT_JSON__


def write_wav(path: Path, pcm: bytes, sample_rate: int, channels: int) -> None:
    bytes_per_sample = 2
    frame_size = channels * bytes_per_sample
    pcm = pcm[: len(pcm) - (len(pcm) % frame_size)]
    byte_rate = sample_rate * frame_size
    block_align = frame_size
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(pcm),
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        16,
        b"data",
        len(pcm),
    )
    path.write_bytes(header + pcm)


async def main() -> None:
    settings = get_settings()
    provider = ProviderRegistry(settings).tts()
    result = await provider.synthesize(TTSInput(text=TEXT))
    if not result.audio_base64:
        raise RuntimeError("TTS returned no audio data for fake microphone verification.")
    if result.encoding != "pcm_s16le":
        raise RuntimeError(f"Fake microphone verification requires pcm_s16le TTS, got {result.encoding}.")
    pcm = base64.b64decode(result.audio_base64)
    sample_rate = int(result.sample_rate or 24000)
    channels = int(result.channels or 1)
    write_wav(OUTPUT, pcm, sample_rate, channels)
    print(f"fake_audio_path={OUTPUT}")
    print(f"tts_model={getattr(provider, 'model', 'unknown')}")
    print(f"sample_rate={sample_rate}")
    print(f"channels={channels}")
    print(f"pcm_bytes={len(pcm)}")


asyncio.run(main())
'@

$GenerateAudio = $GenerateAudio.Replace("__OUTPUT_JSON__", ($FakeAudioPath | ConvertTo-Json -Compress))
$GenerateAudio = $GenerateAudio.Replace("__TEXT_JSON__", ($Text | ConvertTo-Json -Compress))
Set-Content -Path $GenerateAudioScript -Value $GenerateAudio -Encoding UTF8

Push-Location (Join-Path $Root "apps\server")
try {
    $Uv = Resolve-Uv
    $Python = Resolve-Python
    if ($Uv) {
        if (-not $SkipDependencySync) {
            Invoke-CmdExecutable -Executable $Uv -Arguments @("sync")
        }
        Invoke-CmdExecutable -Executable $Uv -Arguments @("run", "python", $GenerateAudioScript)
    } elseif ($Python) {
        Invoke-CmdExecutable -Executable $Python -Arguments @($GenerateAudioScript)
    } else {
        throw "Python 3.11+ or uv is required to generate fake microphone audio."
    }
} finally {
    Pop-Location
}

$RemoteDebuggingPort = Get-FreeTcpPort
$Chrome = Resolve-Chrome
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
const VERIFY_TIMEOUT_MS = 70000;

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
  let receivedAssistantAudioChunks = 0;
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
    if (event.type === "assistant.audio.chunk") receivedAssistantAudioChunks += 1;
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
    await sleep(5500);

    await cdp.send("Runtime.evaluate", {
      expression: `document.querySelector(".mic-panel .toolbar button:nth-of-type(4)").click()`,
      awaitPromise: true,
    });

    await waitFor(() =>
      sentFinalChunks >= 1 &&
      receivedTypes["asr.transcript.final"] >= 1 &&
      receivedTypes["assistant.audio.done"] >= 1,
      VERIFY_TIMEOUT_MS,
      "browser realtime microphone Live response"
    );

    console.log(`web_url=${WEB_URL}`);
    console.log(`sent_audio_chunks=${sentAudioChunks}`);
    console.log(`sent_final_chunks=${sentFinalChunks}`);
    console.log(`asr_text=${asrText.slice(0, 160)}`);
    console.log(`assistant_text=${assistantText.slice(0, 160)}`);
    console.log(`assistant_audio_chunks=${receivedAssistantAudioChunks}`);
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

$ChromeProcess = $null
try {
    $ChromeProcess = Start-Process -FilePath $Chrome -ArgumentList $ChromeArgs -PassThru
    Start-Sleep -Seconds 2

    $Node = Resolve-CommandPath -Name "node.exe" -Candidates @(
        (Join-Path $env:ProgramFiles "nodejs\node.exe")
    )
    if (-not $Node) {
        throw "Node.js is required for browser realtime microphone verification."
    }

    Invoke-CmdExecutable -Executable $Node -Arguments @($CdpScript)
} finally {
    if ($ChromeProcess -and -not $ChromeProcess.HasExited) {
        Stop-Process -Id $ChromeProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if (-not $KeepArtifacts) {
        Remove-Item -Path $WorkDir -Recurse -Force -ErrorAction SilentlyContinue
    } else {
        Write-Host "Browser verification artifacts kept at: $WorkDir"
    }
}

Write-Host "Browser realtime microphone verification finished."
