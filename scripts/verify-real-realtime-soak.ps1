param(
    [int]$DurationMinutes = 20,
    [int]$MaxRounds = 0,
    [int]$Port = 0,
    [string]$Provider = "vertex-ai",
    [string]$AsrProvider = "vertex_ai",
    [string]$VisionProvider = "vertex_ai",
    [string]$LlmProvider = "vertex_ai",
    [string]$TtsProvider = "vertex_ai",
    [string]$RealtimeProvider = "vertex_ai",
    [string]$FakeMicWav = "",
    [string]$SpeechSourceWav = "",
    [string[]]$NoiseProfiles = @(),
    [switch]$GenerateTtsCorpus,
    [switch]$AllowSyntheticTone,
    [string]$WakeWord = "小七",
    [string]$RequestText = "请简短介绍一下你现在能做什么。",
    [string]$TtsText = "",
    [double]$LeadNoiseSeconds = 1.0,
    [double]$TailNoiseSeconds = 1.8,
    [string]$ScreenFrameJpeg = "",
    [switch]$DisableScreenFrames,
    [int]$ChunkMillis = 100,
    [int]$RoundPauseSeconds = 3,
    [int]$RoundTimeoutSeconds = 75,
    [switch]$SkipDependencySync,
    [switch]$KeepArtifacts,
    [string]$ReportPath = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING = "utf-8"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")
Assert-ApiHoldClear -Provider $Provider

$LogDir = Join-Path $Root "data\logs"
$CacheDir = Join-Path $Root "data\cache"
New-Item -ItemType Directory -Force -Path $LogDir, $CacheDir | Out-Null
$RunStamp = (Get-Date).ToString("yyyyMMdd-HHmmss")
if (-not $ReportPath) {
    $ReportPath = Join-Path $LogDir "real-realtime-soak-$RunStamp.json"
}
if (-not $FakeMicWav) {
    $FakeMicWav = Join-Path $CacheDir "modvii-real-realtime-soak.wav"
}
if (-not $TtsText) {
    $TtsText = "$WakeWord，$RequestText"
}
if (-not $NoiseProfiles -or $NoiseProfiles.Count -eq 0) {
    $NoiseProfiles = @("quiet", "low_noise", "white_noise", "fan_low", "keyboard_bursts", "low_voice")
}
if (-not $SpeechSourceWav) {
    $SpeechSourceWav = Join-Path $CacheDir "modvii-real-realtime-soak-speech.wav"
}

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

function ConvertTo-PythonLiteral {
    param([object]$Value)

    if ($null -eq $Value) {
        return "None"
    }
    if ($Value -is [bool]) {
        if ($Value) {
            return "True"
        }
        return "False"
    }
    return ($Value | ConvertTo-Json -Compress)
}

function Resolve-NoiseProfileList {
    param([string[]]$Profiles)

    $Allowed = @("quiet", "low_noise", "white_noise", "fan_low", "keyboard_bursts", "low_voice")
    $Requested = @()
    foreach ($Profile in $Profiles) {
        foreach ($Part in ($Profile -split ",")) {
            $Name = $Part.Trim()
            if (-not $Name) {
                continue
            }
            if ($Name -eq "all") {
                $Requested += $Allowed
                continue
            }
            if ($Allowed -notcontains $Name) {
                throw "Unsupported noise profile '$Name'. Supported profiles: $($Allowed -join ', ')"
            }
            $Requested += $Name
        }
    }
    if ($Requested.Count -eq 0) {
        throw "At least one noise profile is required."
    }
    return @($Requested | Select-Object -Unique)
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

function Read-ScreenFrameBase64 {
    param([string]$Path)

    if ($Path) {
        if (-not (Test-Path $Path)) {
            throw "Screen frame JPEG not found: $Path"
        }
        return [Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path $Path).Path))
    }

    Add-Type -AssemblyName System.Drawing
    $Bitmap = [System.Drawing.Bitmap]::new(64, 64)
    $Graphics = [System.Drawing.Graphics]::FromImage($Bitmap)
    $Stream = [System.IO.MemoryStream]::new()
    try {
        $Graphics.Clear([System.Drawing.Color]::FromArgb(238, 240, 235))
        $Brush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(65, 105, 225))
        try {
            $Graphics.FillRectangle($Brush, 10, 10, 44, 44)
        } finally {
            $Brush.Dispose()
        }
        $Bitmap.Save($Stream, [System.Drawing.Imaging.ImageFormat]::Jpeg)
        return [Convert]::ToBase64String($Stream.ToArray())
    } finally {
        $Stream.Dispose()
        $Graphics.Dispose()
        $Bitmap.Dispose()
    }
}

Import-DotEnvFile -Path (Join-Path $Root ".env")
Import-DotEnvFile -Path (Join-Path $Root "apps\server\.env")

$Uv = Resolve-Uv
$Python = Resolve-Python
if (-not $Uv -and -not $Python) {
    throw "Python 3.11+ or uv is required for real realtime soak verification."
}

if ($Uv -and -not $SkipDependencySync) {
    Push-Location (Join-Path $Root "apps\server")
    try {
        Invoke-CmdExecutable -Executable $Uv -Arguments @("sync", "--group", "dev")
    } finally {
        Pop-Location
    }
}

$AudioPrepScript = Join-Path $env:TEMP "modvii_real_realtime_audio_$([guid]::NewGuid().ToString('N')).py"
$ClientScript = Join-Path $env:TEMP "modvii_real_realtime_soak_$([guid]::NewGuid().ToString('N')).py"

$AudioPrep = @'
import asyncio
import base64
import io
import json
import math
import struct
import sys
import wave
from pathlib import Path

OUTPUT = Path(__OUTPUT_JSON__)
TEXT = __TEXT_JSON__
GENERATE_TTS = __GENERATE_TTS_JSON__
ALLOW_SYNTHETIC_TONE = __ALLOW_SYNTHETIC_TONE_JSON__
TARGET_RATE = 16000


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


def write_wav(path: Path, pcm: bytes, sample_rate: int = TARGET_RATE, channels: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)


def decode_wav_bytes(audio_bytes: bytes) -> tuple[bytes, int, int]:
    with wave.open(io.BytesIO(audio_bytes), "rb") as wav:
        sample_width = wav.getsampwidth()
        if sample_width != 2:
            raise RuntimeError(f"TTS WAV corpus generation requires PCM16 WAV, got sample width {sample_width}.")
        channels = wav.getnchannels()
        sample_rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    samples = pcm16_samples(frames)
    if channels > 1:
        mixed = []
        for index in range(0, len(samples), channels):
            frame = samples[index : index + channels]
            if frame:
                mixed.append(int(sum(frame) / len(frame)))
        samples = mixed
        channels = 1
    return pack_pcm16(samples), sample_rate, channels


def write_synthetic_tone(path: Path) -> dict:
    duration_seconds = 8.0
    samples = []
    for index in range(int(TARGET_RATE * duration_seconds)):
        t = index / TARGET_RATE
        envelope = min(1.0, t / 0.25, (duration_seconds - t) / 0.35)
        value = (
            math.sin(2 * math.pi * 220 * t) * 0.55
            + math.sin(2 * math.pi * 440 * t) * 0.30
            + math.sin(2 * math.pi * 660 * t) * 0.15
        )
        samples.append(int(max(-1.0, min(1.0, value * 0.32 * envelope)) * 32767))
    pcm = pack_pcm16(samples)
    write_wav(path, pcm)
    return {
        "mode": "synthetic-tone",
        "path": str(path),
        "sample_rate": TARGET_RATE,
        "channels": 1,
        "duration_ms": round(len(samples) / TARGET_RATE * 1000),
        "bytes": len(pcm),
        "warning": "Synthetic tone is deterministic but is not a speech-quality ASR corpus.",
    }


def read_existing_wav(path: Path) -> dict:
    with wave.open(str(path), "rb") as wav:
        return {
            "mode": "existing-wav",
            "path": str(path),
            "sample_rate": wav.getframerate(),
            "channels": wav.getnchannels(),
            "duration_ms": round(wav.getnframes() / max(1, wav.getframerate()) * 1000),
            "bytes": path.stat().st_size,
        }


async def write_tts_corpus(path: Path) -> dict:
    sys.path.insert(0, str(Path.cwd()))
    from app.config import get_settings
    from app.contracts.model_io import TTSInput
    from app.providers.registry import ProviderRegistry

    settings = get_settings()
    provider = ProviderRegistry(settings).tts()
    result = await provider.synthesize(TTSInput(text=TEXT))
    if not result.audio_base64:
        raise RuntimeError("TTS returned no audio data for soak corpus generation.")
    source_pcm = base64.b64decode(result.audio_base64)
    if result.encoding == "wav" or result.mime == "audio/wav" or source_pcm[:4] == b"RIFF":
        source_pcm, source_rate, source_channels = decode_wav_bytes(source_pcm)
    elif result.encoding == "pcm_s16le":
        source_rate = int(result.sample_rate or 24000)
        source_channels = int(result.channels or 1)
    else:
        raise RuntimeError(
            f"TTS corpus generation requires pcm_s16le or wav audio, got {result.encoding}. "
            "Provide -FakeMicWav or configure a PCM TTS response format."
        )
    if source_channels != 1:
        raise RuntimeError(f"TTS corpus generation requires mono audio, got {source_channels} channels.")
    samples = pcm16_samples(source_pcm)
    pcm = pack_pcm16(resample(samples, source_rate, TARGET_RATE))
    if not pcm:
        raise RuntimeError("Generated TTS corpus was empty after resampling.")
    write_wav(path, pcm)
    return {
        "mode": "tts-corpus",
        "path": str(path),
        "tts_model": getattr(provider, "model", "unknown"),
        "sample_rate": TARGET_RATE,
        "source_sample_rate": source_rate,
        "channels": 1,
        "duration_ms": round(len(pcm) / 2 / TARGET_RATE * 1000),
        "bytes": len(pcm),
        "text": TEXT,
    }


async def main() -> None:
    if GENERATE_TTS:
        result = await write_tts_corpus(OUTPUT)
    elif OUTPUT.exists():
        result = read_existing_wav(OUTPUT)
    elif ALLOW_SYNTHETIC_TONE:
        result = write_synthetic_tone(OUTPUT)
    else:
        raise RuntimeError(
            f"Fake microphone WAV not found: {OUTPUT}. "
            "Rerun with -GenerateTtsCorpus to create fixed speech audio through the configured TTS provider, "
            "pass -FakeMicWav, or use -AllowSyntheticTone for a non-speech fallback."
        )
    print(json.dumps(result, ensure_ascii=False))


asyncio.run(main())
'@

$AudioPrep = $AudioPrep.Replace("__OUTPUT_JSON__", ($SpeechSourceWav | ConvertTo-Json -Compress))
$AudioPrep = $AudioPrep.Replace("__TEXT_JSON__", ($TtsText | ConvertTo-Json -Compress))
$AudioPrep = $AudioPrep.Replace("__GENERATE_TTS_JSON__", (ConvertTo-PythonLiteral $GenerateTtsCorpus.IsPresent))
$AudioPrep = $AudioPrep.Replace("__ALLOW_SYNTHETIC_TONE_JSON__", (ConvertTo-PythonLiteral $AllowSyntheticTone.IsPresent))
Set-Content -Path $AudioPrepScript -Value $AudioPrep -Encoding UTF8

$AudioEnv = @{
    TTS_PROVIDER = $TtsProvider
}
$PreviousAudioEnv = Set-ProcessEnv -Values $AudioEnv
try {
    Push-Location (Join-Path $Root "apps\server")
    try {
        if ($GenerateTtsCorpus) {
            if ($Uv) {
                Invoke-ApiCommand -Executable $Uv -Arguments @("run", "python", $AudioPrepScript) -Provider $Provider -CommandName "Real realtime soak TTS corpus generation"
            } else {
                Invoke-ApiCommand -Executable $Python -Arguments @($AudioPrepScript) -Provider $Provider -CommandName "Real realtime soak TTS corpus generation"
            }
        } else {
            if ($Uv) {
                Invoke-CmdExecutable -Executable $Uv -Arguments @("run", "python", $AudioPrepScript)
            } else {
                Invoke-CmdExecutable -Executable $Python -Arguments @($AudioPrepScript)
            }
        }
    } finally {
        Pop-Location
    }
} finally {
    Restore-ProcessEnv -Previous $PreviousAudioEnv
}

$AudioCorpusHelper = Join-Path $PSScriptRoot "modvii_audio_corpus.py"
if (-not (Test-Path $AudioCorpusHelper)) {
    throw "MODVII audio corpus helper not found: $AudioCorpusHelper"
}

$ResolvedNoiseProfiles = Resolve-NoiseProfileList -Profiles $NoiseProfiles
$AudioFixtures = @()
foreach ($NoiseProfile in $ResolvedNoiseProfiles) {
    $ProfileAudioPath = $FakeMicWav
    if ($ResolvedNoiseProfiles.Count -gt 1) {
        $ProfileAudioPath = Join-Path $CacheDir "modvii-real-realtime-soak-$NoiseProfile.wav"
    }
    $ProfileMetadataPath = [System.IO.Path]::ChangeExtension($ProfileAudioPath, ".json")
    $CorpusArgs = @(
        $AudioCorpusHelper,
        "--output", $ProfileAudioPath,
        "--profile", $NoiseProfile,
        "--source-wav", $SpeechSourceWav,
        "--wake-word", $WakeWord,
        "--request-text", $RequestText,
        "--text", $TtsText,
        "--lead-seconds", ([string]$LeadNoiseSeconds),
        "--tail-seconds", ([string]$TailNoiseSeconds),
        "--metadata-output", $ProfileMetadataPath
    )
    if ($Python) {
        Invoke-CmdExecutable -Executable $Python -Arguments $CorpusArgs
    } else {
        Push-Location (Join-Path $Root "apps\server")
        try {
            Invoke-CmdExecutable -Executable $Uv -Arguments (@("run", "python") + $CorpusArgs)
        } finally {
            Pop-Location
        }
    }
    $ProfileMetadata = Get-Content -Path $ProfileMetadataPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $AudioFixtures += [ordered]@{
        profile = $NoiseProfile
        path = $ProfileAudioPath
        metadata = $ProfileMetadata
    }
}

if ($Port -le 0) {
    $Port = Get-FreeTcpPort
}

$ServerOut = Join-Path $LogDir "real-realtime-soak-server-$RunStamp.out.log"
$ServerErr = Join-Path $LogDir "real-realtime-soak-server-$RunStamp.err.log"
$ScreenFrameBase64 = Read-ScreenFrameBase64 -Path $ScreenFrameJpeg

$Client = @'
import asyncio
import base64
import json
import math
import re
import statistics
import struct
import time
import urllib.request
import wave
from pathlib import Path
from uuid import uuid4

import websockets

BASE_URL = __BASE_URL_JSON__
REPORT_PATH = Path(__REPORT_PATH_JSON__)
AUDIO_FIXTURES = __AUDIO_FIXTURES_JSON__
SCREEN_FRAME_BASE64 = __SCREEN_FRAME_BASE64_JSON__
SCREEN_FRAME_WIDTH = __SCREEN_FRAME_WIDTH_JSON__
SCREEN_FRAME_HEIGHT = __SCREEN_FRAME_HEIGHT_JSON__
DURATION_SECONDS = __DURATION_SECONDS_JSON__
MAX_ROUNDS = __MAX_ROUNDS_JSON__
CHUNK_MS = __CHUNK_MS_JSON__
ROUND_PAUSE_SECONDS = __ROUND_PAUSE_SECONDS_JSON__
ROUND_TIMEOUT_SECONDS = __ROUND_TIMEOUT_SECONDS_JSON__
SCREEN_FRAMES_ENABLED = __SCREEN_FRAMES_ENABLED_JSON__
PROVIDERS = __PROVIDERS_JSON__


def now_ms() -> int:
    return int(time.time() * 1000)


def post_json(url: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def make_event(event_type: str, session_id: str, payload: dict) -> dict:
    return {
        "id": f"evt_{uuid4().hex[:16]}",
        "type": event_type,
        "session_id": session_id,
        "ts": now_ms(),
        "payload": payload,
    }


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


def read_wav_as_realtime_pcm(path: Path, target_rate: int = 16000) -> tuple[bytes, dict]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        source_rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
        duration_ms = round(wav.getnframes() / max(1, source_rate) * 1000)
    if sample_width != 2:
        raise RuntimeError(f"Fake microphone WAV must be PCM16, got sample width {sample_width}.")
    if channels < 1:
        raise RuntimeError("Fake microphone WAV has no channels.")
    samples = pcm16_samples(frames)
    if channels > 1:
        mixed = []
        for index in range(0, len(samples), channels):
            frame = samples[index : index + channels]
            if frame:
                mixed.append(int(sum(frame) / len(frame)))
        samples = mixed
    pcm = pack_pcm16(resample(samples, source_rate, target_rate))
    if not pcm:
        raise RuntimeError("Fake microphone WAV produced empty realtime PCM.")
    return pcm, {
        "path": str(path),
        "source_sample_rate": source_rate,
        "sample_rate": target_rate,
        "source_channels": channels,
        "channels": 1,
        "source_duration_ms": duration_ms,
        "duration_ms": round(len(pcm) / 2 / target_rate * 1000),
        "pcm_bytes": len(pcm),
    }


def is_429(payload: dict) -> bool:
    text = json.dumps(payload, ensure_ascii=False).lower()
    return (
        "429" in text
        or "resource_exhausted" in text
        or "resource exhausted" in text
        or "rate limit" in text
        or "quota" in text
    )


def is_timeout(payload: dict) -> bool:
    text = json.dumps(payload, ensure_ascii=False).lower()
    return "timeout" in text or "timed out" in text or "deadline" in text


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    rank = (len(ordered) - 1) * percent
    low = int(math.floor(rank))
    high = int(math.ceil(rank))
    if low == high:
        return round(ordered[low], 3)
    fraction = rank - low
    return round(ordered[low] + (ordered[high] - ordered[low]) * fraction, 3)


def summarize_latencies(rounds: list[dict]) -> dict:
    keys = [
        "asr_final",
        "asr_final_after_audio_final",
        "first_assistant_text_delta_after_audio_final",
        "first_assistant_audio_chunk_after_audio_final",
        "assistant_text_final",
        "assistant_text_final_after_audio_final",
        "assistant_audio_done",
        "assistant_audio_done_after_audio_final",
        "round_done",
    ]
    result = {}
    for key in keys:
        values = [float(round_data["latencies_ms"][key]) for round_data in rounds if key in round_data["latencies_ms"]]
        result[key] = {
            "count": len(values),
            "p50": percentile(values, 0.50),
            "p95": percentile(values, 0.95),
            "min": round(min(values), 3) if values else None,
            "max": round(max(values), 3) if values else None,
        }
    return result


def compact_payload(payload: dict) -> dict:
    compact = {}
    for key, value in payload.items():
        if isinstance(value, str):
            compact[key] = value[:240]
        elif isinstance(value, (int, float, bool)) or value is None:
            compact[key] = value
        elif key in {"objects"} and isinstance(value, list):
            compact[key] = value[:3]
        else:
            compact[key] = str(value)[:240]
    return compact


def compact_cost(payload: dict) -> dict:
    keys = [
        "mode",
        "frame_candidates",
        "frames_uploaded",
        "bytes_uploaded",
        "vision_calls",
        "llm_calls",
        "asr_calls",
        "tts_calls",
        "estimated_input_tokens",
        "estimated_output_tokens",
        "estimated_cost_usd",
        "estimated_visual_cost_saved_usd",
        "last_latency_ms",
    ]
    return {key: payload.get(key) for key in keys if key in payload}


async def wait_health() -> dict:
    started = time.monotonic()
    while time.monotonic() - started < 45:
        try:
            health = get_json(f"{BASE_URL.rstrip('/')}/health")
            if health.get("ok"):
                return health
        except Exception:
            pass
        await asyncio.sleep(0.5)
    raise RuntimeError(f"Server health timeout at {BASE_URL}")


async def send_audio(websocket, session_id: str, round_index: int, fixture: dict, round_data: dict) -> None:
    pcm = fixture["pcm"]
    profile = fixture["profile"]
    fixture_metadata = fixture.get("metadata") or {}
    chunk_bytes = max(2, int(16000 * 2 * CHUNK_MS / 1000))
    chunk_bytes -= chunk_bytes % 2
    for offset in range(0, len(pcm), chunk_bytes):
        chunk = pcm[offset : offset + chunk_bytes]
        if not chunk:
            continue
        if "first_audio_sent_perf" not in round_data:
            round_data["first_audio_sent_perf"] = time.perf_counter()
        round_data["audio_chunks_sent"] += 1
        round_data["audio_bytes_sent"] += len(chunk)
        await websocket.send(json.dumps(make_event("client.media.audio_chunk", session_id, {
            "chunk_id": f"real_soak_{round_index}_{profile}_{offset // chunk_bytes}",
            "mime": "audio/pcm;rate=16000",
            "sample_rate": 16000,
            "channels": 1,
            "encoding": "pcm_s16le",
            "data_base64": base64.b64encode(chunk).decode("ascii"),
            "is_final": False,
            "metadata": {
                "source": "real_realtime_soak",
                "round": round_index,
                "noise_profile": profile,
                "speech_start_ms": fixture_metadata.get("speech_start_ms"),
                "speech_end_ms": fixture_metadata.get("speech_end_ms"),
            },
        })))
        await asyncio.sleep(max(0.005, CHUNK_MS / 1000))
    round_data["final_audio_sent_perf"] = time.perf_counter()
    await websocket.send(json.dumps(make_event("client.media.audio_chunk", session_id, {
        "chunk_id": f"real_soak_{round_index}_{profile}_final",
        "mime": "audio/pcm;rate=16000",
        "sample_rate": 16000,
        "channels": 1,
        "encoding": "pcm_s16le",
        "data_base64": "",
        "is_final": True,
        "metadata": {
            "source": "real_realtime_soak",
            "round": round_index,
            "noise_profile": profile,
            "speech_start_ms": fixture_metadata.get("speech_start_ms"),
            "speech_end_ms": fixture_metadata.get("speech_end_ms"),
            "final": True,
        },
    })))


async def send_screen_frames(websocket, session_id: str, round_index: int, round_data: dict) -> None:
    if not SCREEN_FRAMES_ENABLED:
        return
    await asyncio.sleep(0.05)
    for frame_index in range(3):
        frame_id = f"real_soak_screen_{round_index}_{frame_index}"
        await websocket.send(json.dumps(make_event("client.media.frame", session_id, {
            "frame_id": frame_id,
            "mime": "image/jpeg",
            "width": SCREEN_FRAME_WIDTH,
            "height": SCREEN_FRAME_HEIGHT,
            "quality": 0.72,
            "capture_reason": "screen_stream",
            "scene_hash": f"real_soak_{round_index}_{frame_index}",
            "data_base64": SCREEN_FRAME_BASE64,
            "prompt": "MODVII soak concurrent screen capture placeholder. Prefer preserving realtime voice latency.",
        })))
        round_data["screen_frames_sent"] += 1
        await asyncio.sleep(0.35)


def record_event(round_data: dict, event: dict, round_started: float) -> None:
    event_type = str(event.get("type") or "unknown")
    payload = event.get("payload") or {}
    elapsed = (time.perf_counter() - round_started) * 1000
    round_data["event_counts"][event_type] = round_data["event_counts"].get(event_type, 0) + 1
    round_data["trace"].append({
        "type": event_type,
        "elapsed_ms": round(elapsed, 3),
        "payload": compact_payload(payload if isinstance(payload, dict) else {"value": payload}),
    })
    if event_type == "error":
        code = str(payload.get("code") or "unknown") if isinstance(payload, dict) else "unknown"
        round_data["error_events"].append(payload)
        round_data["api_error_codes"][code] = round_data["api_error_codes"].get(code, 0) + 1
        if isinstance(payload, dict) and is_429(payload):
            round_data["rate_limit_429_count"] += 1
        if isinstance(payload, dict) and is_timeout(payload):
            round_data["timeout_count"] += 1
    elif event_type == "cost.update":
        if isinstance(payload, dict):
            cost = compact_cost(payload)
            round_data["cost_updates"].append(cost)
            round_data["last_cost_update"] = cost
            if round_data.get("assistant_audio_done") and round_data.get("auto_returned_to_listening"):
                round_data["final_cost_after_completion"] = True
    elif event_type == "server.session.state":
        if isinstance(payload, dict):
            round_data["last_session_state"] = compact_payload(payload)
            if payload.get("status") == "listening" and not payload.get("response_in_progress"):
                round_data["auto_returned_to_listening"] = True
    elif event_type == "vision.summary":
        round_data["vision_summary_updates"] += 1
        if isinstance(payload, dict):
            round_data["last_vision_summary"] = compact_payload(payload)
    elif event_type == "assistant.text.delta":
        if "first_assistant_text_delta_perf" not in round_data:
            round_data["first_assistant_text_delta_perf"] = time.perf_counter()
            if "final_audio_sent_perf" in round_data:
                round_data["latencies_ms"]["first_assistant_text_delta_after_audio_final"] = round(
                    (round_data["first_assistant_text_delta_perf"] - round_data["final_audio_sent_perf"]) * 1000,
                    3,
                )
    elif event_type == "asr.transcript.final":
        round_data["asr_final"] = str(payload.get("text") or "") if isinstance(payload, dict) else ""
        if "first_audio_sent_perf" in round_data:
            round_data["latencies_ms"]["asr_final"] = round(
                (time.perf_counter() - round_data["first_audio_sent_perf"]) * 1000,
                3,
            )
        if "final_audio_sent_perf" in round_data:
            round_data["latencies_ms"]["asr_final_after_audio_final"] = round(
                (time.perf_counter() - round_data["final_audio_sent_perf"]) * 1000,
                3,
            )
    elif event_type == "assistant.text.final":
        round_data["assistant_text_final"] = str(payload.get("text") or "") if isinstance(payload, dict) else ""
        if "first_audio_sent_perf" in round_data:
            round_data["latencies_ms"]["assistant_text_final"] = round(
                (time.perf_counter() - round_data["first_audio_sent_perf"]) * 1000,
                3,
            )
        if "final_audio_sent_perf" in round_data:
            round_data["latencies_ms"]["assistant_text_final_after_audio_final"] = round(
                (time.perf_counter() - round_data["final_audio_sent_perf"]) * 1000,
                3,
            )
    elif event_type == "assistant.audio.done":
        round_data["assistant_audio_done"] = payload
        if "first_audio_sent_perf" in round_data:
            round_data["latencies_ms"]["assistant_audio_done"] = round(
                (time.perf_counter() - round_data["first_audio_sent_perf"]) * 1000,
                3,
            )
        if "final_audio_sent_perf" in round_data:
            round_data["latencies_ms"]["assistant_audio_done_after_audio_final"] = round(
                (time.perf_counter() - round_data["final_audio_sent_perf"]) * 1000,
                3,
            )
    elif event_type == "assistant.audio.chunk":
        round_data["assistant_audio_chunks"] += 1
        if "first_assistant_audio_chunk_perf" not in round_data:
            round_data["first_assistant_audio_chunk_perf"] = time.perf_counter()
            if "final_audio_sent_perf" in round_data:
                round_data["latencies_ms"]["first_assistant_audio_chunk_after_audio_final"] = round(
                    (round_data["first_assistant_audio_chunk_perf"] - round_data["final_audio_sent_perf"]) * 1000,
                    3,
                )


async def run_round(websocket, session_id: str, round_index: int, fixture: dict) -> dict:
    started = time.perf_counter()
    fixture_metadata = fixture.get("metadata") or {}
    round_data = {
        "round": round_index,
        "noise_profile": fixture["profile"],
        "audio_path": fixture["path"],
        "speech_start_ms": fixture_metadata.get("speech_start_ms"),
        "speech_end_ms": fixture_metadata.get("speech_end_ms"),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "trace": [],
        "event_counts": {},
        "error_events": [],
        "api_error_codes": {},
        "rate_limit_429_count": 0,
        "timeout_count": 0,
        "asr_final": "",
        "assistant_text_final": "",
        "assistant_audio_done": None,
        "assistant_audio_chunks": 0,
        "audio_chunks_sent": 0,
        "audio_bytes_sent": 0,
        "screen_frames_sent": 0,
        "vision_summary_updates": 0,
        "last_vision_summary": None,
        "auto_returned_to_listening": False,
        "last_session_state": None,
        "cost_updates": [],
        "last_cost_update": None,
        "final_cost_after_completion": False,
        "latencies_ms": {},
    }
    await websocket.send(json.dumps(make_event("client.debug.ping", session_id, {"source": "real_realtime_soak", "round": round_index})))
    audio_task = asyncio.create_task(send_audio(websocket, session_id, round_index, fixture, round_data))
    frame_task = asyncio.create_task(send_screen_frames(websocket, session_id, round_index, round_data))
    deadline = time.monotonic() + ROUND_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        complete = (
            audio_task.done()
            and frame_task.done()
            and round_data["assistant_audio_done"]
            and round_data["auto_returned_to_listening"]
            and round_data["final_cost_after_completion"]
            and (not SCREEN_FRAMES_ENABLED or round_data["vision_summary_updates"] > 0)
        )
        if complete:
            break
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=0.5)
        except asyncio.TimeoutError:
            continue
        event = json.loads(raw)
        record_event(round_data, event, started)
        if round_data["rate_limit_429_count"] > 0:
            break
    await audio_task
    await frame_task
    round_data["latencies_ms"]["round_done"] = round((time.perf_counter() - started) * 1000, 3)
    round_data.pop("first_audio_sent_perf", None)
    round_data.pop("final_audio_sent_perf", None)
    round_data.pop("first_assistant_text_delta_perf", None)
    round_data.pop("first_assistant_audio_chunk_perf", None)
    if not round_data["asr_final"]:
        round_data["error_events"].append({"code": "missing_asr_final", "detail": "No asr.transcript.final received before round timeout."})
    if not round_data["assistant_text_final"]:
        round_data["error_events"].append({"code": "missing_assistant_text_final", "detail": "No assistant.text.final received before round timeout."})
    if not round_data["assistant_audio_done"]:
        round_data["error_events"].append({"code": "missing_assistant_audio_done", "detail": "No assistant.audio.done received before round timeout."})
        round_data["timeout_count"] += 1
    if not round_data["auto_returned_to_listening"]:
        round_data["error_events"].append({"code": "missing_listening_state", "detail": "No listening server.session.state received before round timeout."})
        round_data["timeout_count"] += 1
    if SCREEN_FRAMES_ENABLED and round_data["vision_summary_updates"] <= 0:
        round_data["error_events"].append({"code": "missing_vision_summary", "detail": "No vision.summary received before round timeout."})
        round_data["timeout_count"] += 1
    return round_data


def summarize(report: dict) -> None:
    rounds = report["rounds"]
    event_counts = {}
    api_error_codes = {}
    error_events = []
    rate_limit_429_count = 0
    timeout_count = 0
    cost_update_count = 0
    final_cost_update = None
    for round_data in rounds:
        for key, value in round_data["event_counts"].items():
            event_counts[key] = event_counts.get(key, 0) + value
        for key, value in round_data["api_error_codes"].items():
            api_error_codes[key] = api_error_codes.get(key, 0) + value
        rate_limit_429_count += int(round_data.get("rate_limit_429_count") or 0)
        timeout_count += int(round_data.get("timeout_count") or 0)
        cost_update_count += len(round_data.get("cost_updates") or [])
        if round_data.get("last_cost_update"):
            final_cost_update = round_data["last_cost_update"]
        for event in round_data["error_events"]:
            error_events.append({"round": round_data["round"], "payload": event})
    report["summary"] = {
        "rounds": len(rounds),
        "failed_rounds": sum(1 for round_data in rounds if round_data["error_events"]),
        "noise_profiles": sorted({round_data.get("noise_profile") for round_data in rounds if round_data.get("noise_profile")}),
        "event_counts": event_counts,
        "error_events": error_events,
        "api_error_codes": api_error_codes,
        "rate_limit_429_count": rate_limit_429_count,
        "timeout_count": timeout_count,
        "auto_returned_to_listening_rounds": sum(1 for round_data in rounds if round_data.get("auto_returned_to_listening")),
        "vision_summary_updates": sum(int(round_data.get("vision_summary_updates") or 0) for round_data in rounds),
        "cost_update_count": cost_update_count,
        "final_cost_update": final_cost_update,
        "latencies_ms": summarize_latencies(rounds),
    }


async def main() -> None:
    fixtures = []
    for fixture in AUDIO_FIXTURES:
        pcm, audio_info = read_wav_as_realtime_pcm(Path(fixture["path"]))
        metadata = fixture.get("metadata") or {}
        fixtures.append({
            "profile": fixture["profile"],
            "path": fixture["path"],
            "pcm": pcm,
            "audio": audio_info,
            "metadata": metadata,
        })
    if not fixtures:
        raise RuntimeError("No audio fixtures were configured.")
    report = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_url": BASE_URL,
        "providers": PROVIDERS,
        "duration_seconds": DURATION_SECONDS,
        "max_rounds": MAX_ROUNDS,
        "chunk_ms": CHUNK_MS,
        "round_pause_seconds": ROUND_PAUSE_SECONDS,
        "round_timeout_seconds": ROUND_TIMEOUT_SECONDS,
        "audio": {
            "fixtures": [
                {
                    "profile": fixture["profile"],
                    "path": fixture["path"],
                    "audio": fixture["audio"],
                    "metadata": fixture["metadata"],
                }
                for fixture in fixtures
            ],
        },
        "screen": {
            "enabled": SCREEN_FRAMES_ENABLED,
            "mime": "image/jpeg",
            "capture_reason": "screen_stream",
            "width": SCREEN_FRAME_WIDTH,
            "height": SCREEN_FRAME_HEIGHT,
            "frames_per_round": 3 if SCREEN_FRAMES_ENABLED else 0,
            "placeholder_bytes": len(base64.b64decode(SCREEN_FRAME_BASE64)) if SCREEN_FRAMES_ENABLED else 0,
        },
        "rounds": [],
        "summary": {},
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        report["health"] = await wait_health()
        session = post_json(f"{BASE_URL.rstrip('/')}/api/session", {})
        session_id = session["session_id"]
        report["session_id"] = session_id
        ws_url = f"{BASE_URL.rstrip('/').replace('http://', 'ws://').replace('https://', 'wss://')}/ws/session/{session_id}"
        end_at = time.monotonic() + DURATION_SECONDS
        round_index = 0
        async with websockets.connect(ws_url, max_size=32 * 1024 * 1024) as websocket:
            while time.monotonic() < end_at:
                if MAX_ROUNDS and round_index >= MAX_ROUNDS:
                    break
                round_index += 1
                fixture = fixtures[(round_index - 1) % len(fixtures)]
                round_data = await run_round(websocket, session_id, round_index, fixture)
                report["rounds"].append(round_data)
                summarize(report)
                REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                if round_data["rate_limit_429_count"] > 0:
                    break
                await asyncio.sleep(ROUND_PAUSE_SECONDS)
    except Exception as exc:
        report["fatal_error"] = f"{type(exc).__name__}: {exc}"
        summarize(report)
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    summarize(report)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(REPORT_PATH), "summary": report["summary"]}, ensure_ascii=False, indent=2))
    if report["summary"]["rate_limit_429_count"] > 0:
        raise RuntimeError("Real realtime soak observed 429/quota/rate-limit events.")
    if report["summary"]["failed_rounds"] > 0:
        raise RuntimeError(f"Real realtime soak failed {report['summary']['failed_rounds']} round(s).")


asyncio.run(main())
'@

$Providers = [ordered]@{
    asr = $AsrProvider
    vision = $VisionProvider
    llm = $LlmProvider
    tts = $TtsProvider
    realtime = $RealtimeProvider
}
$Client = $Client.Replace("__BASE_URL_JSON__", ("http://127.0.0.1:$Port" | ConvertTo-Json -Compress))
$Client = $Client.Replace("__REPORT_PATH_JSON__", ($ReportPath | ConvertTo-Json -Compress))
$AudioFixturesJson = ConvertTo-Json -InputObject @($AudioFixtures) -Depth 12 -Compress
$Client = $Client.Replace("__AUDIO_FIXTURES_JSON__", $AudioFixturesJson)
$Client = $Client.Replace("__SCREEN_FRAME_BASE64_JSON__", ($ScreenFrameBase64 | ConvertTo-Json -Compress))
$Client = $Client.Replace("__SCREEN_FRAME_WIDTH_JSON__", (64 | ConvertTo-Json -Compress))
$Client = $Client.Replace("__SCREEN_FRAME_HEIGHT_JSON__", (64 | ConvertTo-Json -Compress))
$Client = $Client.Replace("__DURATION_SECONDS_JSON__", (($DurationMinutes * 60) | ConvertTo-Json -Compress))
$Client = $Client.Replace("__MAX_ROUNDS_JSON__", ($MaxRounds | ConvertTo-Json -Compress))
$Client = $Client.Replace("__CHUNK_MS_JSON__", ($ChunkMillis | ConvertTo-Json -Compress))
$Client = $Client.Replace("__ROUND_PAUSE_SECONDS_JSON__", ($RoundPauseSeconds | ConvertTo-Json -Compress))
$Client = $Client.Replace("__ROUND_TIMEOUT_SECONDS_JSON__", ($RoundTimeoutSeconds | ConvertTo-Json -Compress))
$Client = $Client.Replace("__SCREEN_FRAMES_ENABLED_JSON__", (ConvertTo-PythonLiteral (-not $DisableScreenFrames.IsPresent)))
$Client = $Client.Replace("__PROVIDERS_JSON__", ($Providers | ConvertTo-Json -Compress))
Set-Content -Path $ClientScript -Value $Client -Encoding UTF8

$ServerEnv = @{
    APP_NAME = "MODVII"
    WAKE_WORD = "小七"
    SERVER_HOST = "127.0.0.1"
    SERVER_PORT = "$Port"
    WEB_ORIGIN = "http://127.0.0.1:$Port"
    ASR_PROVIDER = $AsrProvider
    VISION_PROVIDER = $VisionProvider
    LLM_PROVIDER = $LlmProvider
    TTS_PROVIDER = $TtsProvider
    REALTIME_PROVIDER = $RealtimeProvider
    AUDIO_INPUT_SAMPLE_RATE = "16000"
    DATA_DIR = (Join-Path $Root "data")
}

$PreviousServerEnv = Set-ProcessEnv -Values $ServerEnv
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
    Restore-ProcessEnv -Previous $PreviousServerEnv
}

try {
    Push-Location (Join-Path $Root "apps\server")
    try {
        if ($Uv) {
            Invoke-ApiCommand -Executable $Uv -Arguments @("run", "python", $ClientScript) -Provider $Provider -CommandName "Real realtime soak"
        } else {
            Invoke-ApiCommand -Executable $Python -Arguments @($ClientScript) -Provider $Provider -CommandName "Real realtime soak"
        }
    } finally {
        Pop-Location
    }
} finally {
    Stop-ProcessTree -Process $Server
    if (-not $KeepArtifacts) {
        Remove-Item -Path $AudioPrepScript, $ClientScript -Force -ErrorAction SilentlyContinue
    } else {
        Write-Host "Real realtime soak temp scripts kept:"
        Write-Host "  $AudioPrepScript"
        Write-Host "  $ClientScript"
    }
}

Write-Host "Real realtime soak report: $ReportPath"
Write-Host "Server logs: $ServerOut / $ServerErr"
