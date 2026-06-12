param(
    [string]$Project,
    [string]$Location = "global",
    [string]$LlmModel = "gemini-2.5-flash",
    [string]$VisionModel = "gemini-2.5-flash",
    [string]$AsrModel = "gemini-live-2.5-flash-native-audio",
    [string]$RealtimeModel = "gemini-live-2.5-flash-native-audio",
    [string]$TtsModel = "gemini-3.1-flash-tts-preview",
    [string]$TtsVoice = "Kore",
    [ValidateSet("vertex_ai", "gemini", "mock")]
    [string]$AsrProvider = "vertex_ai",
    [ValidateSet("vertex_ai", "gemini", "mock")]
    [string]$TtsProvider = "vertex_ai",
    [ValidateSet("vertex_ai", "gemini", "mock", "none")]
    [string]$RealtimeProvider = "vertex_ai",
    [ValidateSet("vertex_ai", "mock")]
    [string]$VisionProvider = "vertex_ai",
    [string]$GoogleApplicationCredentials = "",
    [switch]$SkipEnableApi,
    [switch]$SkipVerify
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")

$EnvPath = Join-Path $Root ".env"
$EnvExamplePath = Join-Path $Root ".env.example"
$Gcloud = Resolve-Gcloud

if ($Gcloud -and -not $Project) {
    $Project = (& $Gcloud config get-value project 2>$null).Trim()
}

if (-not $Project -or $Project -eq "(unset)") {
    throw "No Google Cloud project is configured. Rerun with -Project <PROJECT_ID>."
}

if ($Gcloud) {
    & $Gcloud config set project $Project | Out-Host

    try {
        & $Gcloud auth application-default set-quota-project $Project | Out-Host
    } catch {
        Write-Warning "Could not set ADC quota project automatically. If verification fails, run: gcloud auth application-default set-quota-project $Project"
    }

    $AdcTokenProbe = (& $Gcloud auth application-default print-access-token 2>$null)
    if (-not $AdcTokenProbe -and -not $GoogleApplicationCredentials) {
        throw "Application Default Credentials are not ready. Run: gcloud auth application-default login"
    }
    $AdcTokenProbe = $null

    if (-not $SkipEnableApi) {
        & $Gcloud services enable aiplatform.googleapis.com --project $Project | Out-Host
    }
} elseif (-not $GoogleApplicationCredentials) {
    throw "gcloud was not found and -GoogleApplicationCredentials was not provided."
} else {
    Write-Warning "gcloud was not found. Writing .env from the provided project and credentials path."
}

if (Test-Path $EnvPath) {
    $BackupPath = Join-Path $Root ".env.before-vertex-ai"
    Copy-Item $EnvPath $BackupPath -Force
}

if (-not $GoogleApplicationCredentials) {
    $DefaultAdc = Join-Path $env:APPDATA "gcloud\application_default_credentials.json"
    if (Test-Path $DefaultAdc) {
        $GoogleApplicationCredentials = $DefaultAdc
    }
}

$EnvValues = @{
    "ASR_PROVIDER" = $AsrProvider
    "LLM_PROVIDER" = "vertex_ai"
    "VISION_PROVIDER" = $VisionProvider
    "TTS_PROVIDER" = $TtsProvider
    "REALTIME_PROVIDER" = $RealtimeProvider
    "VERTEX_AI_PROJECT" = $Project
    "VERTEX_AI_LOCATION" = $Location
    "VERTEX_AI_API_ENDPOINT" = "https://aiplatform.googleapis.com"
    "VERTEX_AI_LLM_MODEL" = $LlmModel
    "VERTEX_AI_VISION_MODEL" = $VisionModel
    "VERTEX_AI_ASR_MODEL" = $AsrModel
    "VERTEX_AI_REALTIME_MODEL" = $RealtimeModel
    "VERTEX_AI_TTS_MODEL" = $TtsModel
    "VERTEX_AI_TTS_VOICE" = $TtsVoice
    "AUDIO_INPUT_SAMPLE_RATE" = "16000"
    "AUDIO_OUTPUT_SAMPLE_RATE" = "24000"
    "AUDIO_CHANNELS" = "1"
    "AUDIO_TRANSCRIPTION_LANGUAGE" = "zh-CN"
}
if ($GoogleApplicationCredentials) {
    $EnvValues["GOOGLE_APPLICATION_CREDENTIALS"] = $GoogleApplicationCredentials
}

Set-DotEnvValues -Path $EnvPath -ExamplePath $EnvExamplePath -Values $EnvValues

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
