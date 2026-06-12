param(
    [string]$Prompt = "Answer in one short Chinese sentence: AstraLive Live API is connected.",
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
from app.providers.registry import ProviderRegistry


async def main() -> None:
    settings = get_settings()
    provider = ProviderRegistry(settings).realtime()
    if provider is None:
        raise RuntimeError("REALTIME_PROVIDER is not configured. Use vertex_ai or gemini.")

    result = await provider.respond_to_text(
        __PROMPT_JSON__,
        {"system_instruction": "You are AstraLive's connection verifier. Answer in one short Chinese sentence."},
    )
    audio_bytes = 0
    for chunk in result.audio_chunks:
        if chunk.audio_base64:
            audio_bytes += len(chunk.audio_base64)

    print(f"provider={provider.provider_name}")
    print(f"model={provider.model}")
    print(f"input_text={result.input_text[:120]}")
    print(f"output_text={result.output_text[:120]}")
    print(f"audio_chunks={len(result.audio_chunks)}")
    print(f"audio_base64_chars={audio_bytes}")
    if not result.output_text and not result.audio_chunks:
        raise RuntimeError("Live API returned no text transcription and no audio chunks.")


asyncio.run(main())
'@

$PromptJson = $Prompt | ConvertTo-Json -Compress
$VerifyScript = $VerifyScript.Replace("__PROMPT_JSON__", $PromptJson)
$TempScript = Join-Path $env:TEMP "astralive_verify_vertex_live.py"
Set-Content -Path $TempScript -Value $VerifyScript -Encoding UTF8

Push-Location (Join-Path $Root "apps\server")
try {
    $Uv = Resolve-Uv
    $Python = Resolve-Python
    if ($Uv) {
        if (-not $SkipDependencySync) {
            Invoke-CmdExecutable -Executable $Uv -Arguments @("sync")
        }
        Invoke-CmdExecutable -Executable $Uv -Arguments @("run", "python", $TempScript)
    } elseif ($Python) {
        Invoke-CmdExecutable -Executable $Python -Arguments @($TempScript)
    } else {
        throw "Python 3.11+ or uv is required to verify Gemini Live."
    }
} finally {
    Pop-Location
    Remove-Item -Path $TempScript -Force -ErrorAction SilentlyContinue
}

Write-Host "Gemini Live verification finished."
