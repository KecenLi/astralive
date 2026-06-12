param(
    [string]$KeyFile,
    [string]$LlmModel = "gemini-3.5-flash",
    [string]$VisionModel = "gemini-3.5-flash",
    [ValidateSet("gemini", "mock")]
    [string]$VisionProvider = "gemini",
    [switch]$KeepKeyFile,
    [switch]$SkipVerify
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")

if (-not $KeyFile) {
    $KeyFile = Join-Path $Root "gemini_key.txt"
}

$EnvPath = Join-Path $Root ".env"
$EnvExamplePath = Join-Path $Root ".env.example"
$GeminiBaseUrl = "https://generativelanguage.googleapis.com/v1beta/openai/"

if (-not (Test-Path $KeyFile)) {
    throw "Gemini key file was not found: $KeyFile"
}

$ApiKey = (Get-Content -Path $KeyFile -Raw).Trim()
if (-not $ApiKey) {
    throw "Gemini key file is empty: $KeyFile"
}
if ($ApiKey -match "\s") {
    throw "Gemini key file must contain only the API key, with no spaces or extra lines."
}

if (Test-Path $EnvPath) {
    $BackupPath = Join-Path $Root ".env.before-gemini"
    Copy-Item $EnvPath $BackupPath -Force
}

Set-DotEnvValues -Path $EnvPath -ExamplePath $EnvExamplePath -Values @{
    "LLM_PROVIDER" = "gemini"
    "VISION_PROVIDER" = $VisionProvider
    "GEMINI_BASE_URL" = $GeminiBaseUrl
    "GEMINI_API_KEY" = $ApiKey
    "GEMINI_LLM_MODEL" = $LlmModel
    "GEMINI_VISION_MODEL" = $VisionModel
}

if (-not $KeepKeyFile) {
    Remove-Item -Path $KeyFile -Force
}

if ($SkipVerify) {
    Write-Host "Gemini configuration written to .env. Verification was skipped."
    exit 0
}

$Python = Join-Path $Root "apps\server\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = Resolve-Python
}
if (-not $Python) {
    throw "Python is required to verify Gemini configuration."
}

$VerifyScript = @'
import asyncio

from app.config import get_settings
from app.contracts.model_io import ChatMessage, DialogueInput
from app.providers.registry import ProviderRegistry


async def main() -> None:
    settings = get_settings()
    provider = ProviderRegistry(settings).llm()
    result = await provider.complete(
        DialogueInput(messages=[ChatMessage(role="user", content="用一句中文回复：Gemini 已连接。")])
    )
    print(f"provider={provider.provider_name}")
    print(f"model={provider.model}")
    print(f"text={result.text[:120]}")


asyncio.run(main())
'@

$TempScript = Join-Path $env:TEMP "astralive_verify_gemini.py"
Set-Content -Path $TempScript -Value $VerifyScript -Encoding UTF8
Push-Location (Join-Path $Root "apps\server")
try {
    & $Python $TempScript
} finally {
    Pop-Location
    Remove-Item -Path $TempScript -Force -ErrorAction SilentlyContinue
}

Write-Host "Gemini configuration verified. Restart the backend and web dev server if they are already running."
