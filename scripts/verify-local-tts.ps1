param(
    [string]$Text = "MODVII local prompt audio test.",
    [switch]$SkipDependencySync
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH = "."
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")

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

$Verifier = Join-Path $env:TEMP "modvii_verify_local_tts_$([guid]::NewGuid().ToString('N')).py"
$Code = @'
import asyncio
import json
import time

from app.config import get_settings
from app.contracts.model_io import TTSInput
from app.providers.registry import ProviderRegistry

TEXT = __TEXT_JSON__


async def main() -> None:
    settings = get_settings()
    provider = ProviderRegistry(settings).tts()
    try:
        started = time.perf_counter()
        result = await provider.synthesize(TTSInput(text=TEXT, emotion="happy"))
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        print(json.dumps({
            "provider": settings.tts_provider,
            "mime": result.mime,
            "encoding": result.encoding,
            "sample_rate": result.sample_rate,
            "duration_ms": result.duration_ms,
            "audio_chars": len(result.audio_base64),
            "seed": settings.cosyvoice3_seed,
            "worker_script": settings.cosyvoice3_worker_script,
            "elapsed_ms": elapsed_ms,
        }, ensure_ascii=False, indent=2))
    finally:
        close = getattr(provider, "close", None)
        if close:
            await close()


asyncio.run(main())
'@
$Code = $Code.Replace("__TEXT_JSON__", ($Text | ConvertTo-Json -Compress))
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
