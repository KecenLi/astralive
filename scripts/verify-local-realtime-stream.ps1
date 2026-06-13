param(
    [string]$ServerBaseUrl = "http://127.0.0.1:8765",
    [string]$Text = "MODVII realtime audio stream test. Please answer in Chinese.",
    [switch]$SkipDependencySync
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")
Assert-ApiHoldClear -Provider "vertex-ai"

$VerifyScript = @'
import asyncio
import base64
import json
import math
import struct
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import websockets

sys.path.insert(0, str(Path.cwd()))

from app.config import get_settings
from app.contracts.model_io import TTSInput
from app.providers.registry import ProviderRegistry


SERVER_BASE_URL = __SERVER_BASE_URL_JSON__
TEXT = __TEXT_JSON__
TARGET_RATE = 16000
CHUNK_MS = 100


def pcm16_samples(audio_bytes: bytes) -> list[int]:
    sample_count = len(audio_bytes) // 2
    if sample_count == 0:
        return []
    return list(struct.unpack("<" + "h" * sample_count, audio_bytes[: sample_count * 2]))


def resample(samples: list[int], source_rate: int, target_rate: int) -> list[int]:
    if source_rate == target_rate:
        return samples
    if not samples:
        return []
    target_count = max(1, int(len(samples) * target_rate / source_rate))
    ratio = source_rate / target_rate
    output: list[int] = []
    for index in range(target_count):
        position = index * ratio
        left_index = min(int(math.floor(position)), len(samples) - 1)
        right_index = min(left_index + 1, len(samples) - 1)
        fraction = position - left_index
        value = samples[left_index] + (samples[right_index] - samples[left_index]) * fraction
        output.append(max(-32768, min(32767, int(value))))
    return output


def pack_pcm16(samples: list[int]) -> bytes:
    if not samples:
        return b""
    return struct.pack("<" + "h" * len(samples), *samples)


def make_event(event_type: str, session_id: str, payload: dict) -> dict:
    return {
        "id": f"evt_{uuid4().hex[:16]}",
        "type": event_type,
        "session_id": session_id,
        "ts": int(time.time() * 1000),
        "payload": payload,
    }


async def main() -> None:
    settings = get_settings()
    registry = ProviderRegistry(settings)
    tts = registry.tts()
    tts_result = await tts.synthesize(TTSInput(text=TEXT))
    if not tts_result.audio_base64:
        raise RuntimeError("TTS returned no audio data for local realtime stream verification.")

    source_audio = base64.b64decode(tts_result.audio_base64)
    source_samples = pcm16_samples(source_audio)
    target_samples = resample(source_samples, int(tts_result.sample_rate or 24000), TARGET_RATE)
    target_audio = pack_pcm16(target_samples)
    if not target_audio:
        raise RuntimeError("Generated verification audio is empty after resampling.")

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(f"{SERVER_BASE_URL.rstrip('/')}/api/session")
        response.raise_for_status()
        session = response.json()
    session_id = session["session_id"]
    ws_url = f"{SERVER_BASE_URL.rstrip('/').replace('http://', 'ws://').replace('https://', 'wss://')}/ws/session/{session_id}"

    events_seen: dict[str, int] = {}
    asr_text = ""
    assistant_text = ""
    assistant_audio_chunks = 0
    audio_done = False
    chunk_bytes = int(TARGET_RATE * 2 * CHUNK_MS / 1000)

    async with websockets.connect(ws_url, max_size=16 * 1024 * 1024) as websocket:
        for offset in range(0, len(target_audio), chunk_bytes):
            chunk = target_audio[offset : offset + chunk_bytes]
            payload = {
                "chunk_id": f"verify_{offset // chunk_bytes}",
                "mime": f"audio/pcm;rate={TARGET_RATE}",
                "sample_rate": TARGET_RATE,
                "channels": 1,
                "encoding": "pcm_s16le",
                "data_base64": base64.b64encode(chunk).decode("ascii"),
                "is_final": False,
            }
            await websocket.send(json.dumps(make_event("client.media.audio_chunk", session_id, payload)))
            await asyncio.sleep(0.02)

        final_payload = {
            "chunk_id": "verify_final",
            "mime": f"audio/pcm;rate={TARGET_RATE}",
            "sample_rate": TARGET_RATE,
            "channels": 1,
            "encoding": "pcm_s16le",
            "data_base64": "",
            "is_final": True,
        }
        await websocket.send(json.dumps(make_event("client.media.audio_chunk", session_id, final_payload)))

        deadline = asyncio.get_running_loop().time() + 45
        while asyncio.get_running_loop().time() < deadline:
            timeout = max(0.1, min(2.0, deadline - asyncio.get_running_loop().time()))
            try:
                raw_event = await asyncio.wait_for(websocket.recv(), timeout=timeout)
            except TimeoutError:
                continue

            event = json.loads(raw_event)
            event_type = event.get("type", "")
            payload = event.get("payload") or {}
            events_seen[event_type] = events_seen.get(event_type, 0) + 1

            if event_type == "error":
                raise RuntimeError(f"Server returned error during realtime stream verification: {payload}")
            if event_type == "asr.transcript.final":
                asr_text = str(payload.get("text") or "")
            if event_type == "assistant.text.final":
                assistant_text = str(payload.get("text") or "")
            if event_type == "assistant.audio.chunk":
                assistant_audio_chunks += 1
            if event_type == "assistant.audio.done":
                audio_done = True
                break

    if not asr_text:
        raise RuntimeError(f"No final ASR transcript received. events={events_seen}")
    if not audio_done:
        raise RuntimeError(f"No assistant.audio.done received. events={events_seen}")

    print(f"session_id={session_id}")
    print(f"tts_model={getattr(tts, 'model', 'unknown')}")
    print(f"input_audio_bytes={len(target_audio)}")
    print(f"asr_text={asr_text[:160]}")
    print(f"assistant_text={assistant_text[:160]}")
    print(f"assistant_audio_chunks={assistant_audio_chunks}")
    print(f"events_seen={events_seen}")


asyncio.run(main())
'@

$ServerBaseUrlJson = $ServerBaseUrl | ConvertTo-Json -Compress
$TextJson = $Text | ConvertTo-Json -Compress
$VerifyScript = $VerifyScript.Replace("__SERVER_BASE_URL_JSON__", $ServerBaseUrlJson)
$VerifyScript = $VerifyScript.Replace("__TEXT_JSON__", $TextJson)
$TempScript = Join-Path $env:TEMP "modvii_verify_local_realtime_stream.py"
Set-Content -Path $TempScript -Value $VerifyScript -Encoding UTF8

Push-Location (Join-Path $Root "apps\server")
try {
    $Uv = Resolve-Uv
    $Python = Resolve-Python
    if ($Uv) {
        if (-not $SkipDependencySync) {
            Invoke-CmdExecutable -Executable $Uv -Arguments @("sync")
        }
        Invoke-ApiCommand -Executable $Uv -Arguments @("run", "python", $TempScript) -Provider "vertex-ai" -CommandName "Local realtime stream verification"
    } elseif ($Python) {
        Invoke-ApiCommand -Executable $Python -Arguments @($TempScript) -Provider "vertex-ai" -CommandName "Local realtime stream verification"
    } else {
        throw "Python 3.11+ or uv is required to verify the local realtime stream."
    }
} finally {
    Pop-Location
    Remove-Item -Path $TempScript -Force -ErrorAction SilentlyContinue
}

Write-Host "Local realtime stream verification finished."
