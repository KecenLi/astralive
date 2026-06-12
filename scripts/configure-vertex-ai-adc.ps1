param(
    [string]$Project,
    [string]$Location = "global",
    [string]$LlmModel = "gemini-2.5-flash",
    [string]$VisionModel = "gemini-2.5-flash",
    [ValidateSet("vertex_ai", "mock")]
    [string]$VisionProvider = "vertex_ai",
    [switch]$SkipEnableApi,
    [switch]$SkipVerify
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")

$EnvPath = Join-Path $Root ".env"
$EnvExamplePath = Join-Path $Root ".env.example"
$Gcloud = Resolve-Gcloud

if (-not $Gcloud) {
    throw "gcloud was not found. Install Google Cloud CLI or reopen PowerShell after installation."
}

if (-not $Project) {
    $Project = (& $Gcloud config get-value project 2>$null).Trim()
}

if (-not $Project -or $Project -eq "(unset)") {
    throw "No Google Cloud project is configured. Rerun with -Project <PROJECT_ID>."
}

& $Gcloud config set project $Project | Out-Host

try {
    & $Gcloud auth application-default set-quota-project $Project | Out-Host
} catch {
    Write-Warning "Could not set ADC quota project automatically. If verification fails, run: gcloud auth application-default set-quota-project $Project"
}

$AdcTokenProbe = (& $Gcloud auth application-default print-access-token 2>$null)
if (-not $AdcTokenProbe) {
    throw "Application Default Credentials are not ready. Run: gcloud auth application-default login"
}
$AdcTokenProbe = $null

if (-not $SkipEnableApi) {
    & $Gcloud services enable aiplatform.googleapis.com --project $Project | Out-Host
}

if (Test-Path $EnvPath) {
    $BackupPath = Join-Path $Root ".env.before-vertex-ai"
    Copy-Item $EnvPath $BackupPath -Force
}

Set-DotEnvValues -Path $EnvPath -ExamplePath $EnvExamplePath -Values @{
    "LLM_PROVIDER" = "vertex_ai"
    "VISION_PROVIDER" = $VisionProvider
    "VERTEX_AI_PROJECT" = $Project
    "VERTEX_AI_LOCATION" = $Location
    "VERTEX_AI_API_ENDPOINT" = "https://aiplatform.googleapis.com"
    "VERTEX_AI_LLM_MODEL" = $LlmModel
    "VERTEX_AI_VISION_MODEL" = $VisionModel
}

if ($SkipVerify) {
    Write-Host "Vertex AI ADC configuration written to .env. Verification was skipped."
    exit 0
}

$Python = Join-Path $Root "apps\server\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = Resolve-Python
}
if (-not $Python) {
    throw "Python is required to verify Vertex AI configuration."
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
        DialogueInput(messages=[ChatMessage(role="user", content="用一句中文回复：Vertex AI 已连接。")])
    )
    print(f"provider={provider.provider_name}")
    print(f"model={provider.model}")
    print(f"text={result.text[:120]}")


asyncio.run(main())
'@

$TempScript = Join-Path $env:TEMP "astralive_verify_vertex_ai.py"
Set-Content -Path $TempScript -Value $VerifyScript -Encoding UTF8
Push-Location (Join-Path $Root "apps\server")
try {
    & $Python $TempScript
} finally {
    Pop-Location
    Remove-Item -Path $TempScript -Force -ErrorAction SilentlyContinue
}

Write-Host "Vertex AI ADC configuration verified. Restart the backend and web dev server if they are already running."
