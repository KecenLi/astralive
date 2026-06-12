param(
    [string]$Text = "AstraLive text to speech is connected.",
    [switch]$SkipDependencySync
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")

$VerifyScript = @'
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from app.config import get_settings
from app.contracts.model_io import TTSInput
from app.providers.registry import ProviderRegistry


async def main() -> None:
    settings = get_settings()
    provider = ProviderRegistry(settings).tts()
    result = await provider.synthesize(TTSInput(text=__TEXT_JSON__))
    print(f"provider={getattr(provider, 'provider_name', 'unknown')}")
    print(f"model={getattr(provider, 'model', 'unknown')}")
    print(f"mime={result.mime}")
    print(f"encoding={result.encoding}")
    print(f"sample_rate={result.sample_rate}")
    print(f"audio_base64_chars={len(result.audio_base64)}")
    if not result.audio_base64:
        raise RuntimeError("TTS returned no audio data.")


asyncio.run(main())
'@

$TextJson = $Text | ConvertTo-Json -Compress
$VerifyScript = $VerifyScript.Replace("__TEXT_JSON__", $TextJson)
$TempScript = Join-Path $env:TEMP "astralive_verify_vertex_tts.py"
Set-Content -Path $TempScript -Value $VerifyScript -Encoding UTF8

Push-Location (Join-Path $Root "apps\server")
try {
    $Uv = Resolve-Uv
    $Python = Resolve-Python
    if ($Uv) {
        if (-not $SkipDependencySync) {
            & $Uv sync
            if ($LASTEXITCODE -ne 0) {
                throw "uv sync failed with exit code $LASTEXITCODE."
            }
        }
        & $Uv run python $TempScript
        if ($LASTEXITCODE -ne 0) {
            throw "TTS verification failed with exit code $LASTEXITCODE."
        }
    } elseif ($Python) {
        & $Python $TempScript
        if ($LASTEXITCODE -ne 0) {
            throw "TTS verification failed with exit code $LASTEXITCODE."
        }
    } else {
        throw "Python 3.11+ or uv is required to verify Gemini TTS."
    }
} finally {
    Pop-Location
    Remove-Item -Path $TempScript -Force -ErrorAction SilentlyContinue
}

Write-Host "Gemini TTS verification finished."
