param(
    [string]$AudioPath = "",
    [switch]$SkipDependencySync
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH = "."
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")

if (-not $AudioPath) {
    $AudioPath = Join-Path $Root "data\cache\modvii-test-speech.wav"
}
if (-not (Test-Path $AudioPath)) {
    throw "Audio file not found: $AudioPath"
}

Import-DotEnvFile -Path (Join-Path $Root ".env")
Import-DotEnvFile -Path (Join-Path $Root "apps\server\.env")

$Uv = Resolve-Uv
$Python = Resolve-Python
if (-not $Uv -and -not $Python) {
    throw "Python 3.11+ or uv is required."
}

if ($Uv -and -not $SkipDependencySync) {
    Push-Location (Join-Path $Root "apps\server")
    try {
        Invoke-CmdExecutable -Executable $Uv -Arguments @("sync", "--group", "dev")
    } finally {
        Pop-Location
    }
}

$Verifier = Join-Path $env:TEMP "modvii_verify_local_asr_$([guid]::NewGuid().ToString('N')).py"
$Code = @'
import asyncio
import json
import time
from pathlib import Path

from app.config import get_settings
from app.providers.registry import ProviderRegistry

AUDIO_PATH = Path(__AUDIO_PATH_JSON__)


async def main() -> None:
    settings = get_settings()
    provider = ProviderRegistry(settings).asr()
    try:
        started = time.perf_counter()
        result = await provider.transcribe(AUDIO_PATH.read_bytes(), {"encoding": "wav", "mime": "audio/wav"})
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        print(json.dumps({
            "provider": settings.asr_provider,
            "text": result.text,
            "raw": result.raw,
            "elapsed_ms": elapsed_ms,
        }, ensure_ascii=False, indent=2))
    finally:
        close = getattr(provider, "close", None)
        if close:
            await close()


asyncio.run(main())
'@
$Code = $Code.Replace("__AUDIO_PATH_JSON__", ($AudioPath | ConvertTo-Json -Compress))
Set-Content -Path $Verifier -Value $Code -Encoding UTF8

Push-Location (Join-Path $Root "apps\server")
try {
    if ($Uv) {
        Invoke-CmdExecutable -Executable $Uv -Arguments @("run", "python", $Verifier)
    } else {
        Invoke-CmdExecutable -Executable $Python -Arguments @($Verifier)
    }
} finally {
    Pop-Location
    Remove-Item -Path $Verifier -Force -ErrorAction SilentlyContinue
}
