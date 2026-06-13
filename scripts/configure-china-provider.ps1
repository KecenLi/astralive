param(
    [ValidateSet("dashscope-hk", "dashscope-cn", "siliconflow", "volcengine", "qianfan-aistudio")]
    [string]$Profile = "dashscope-hk",
    [string]$ApiKey,
    [string]$LlmModel = "",
    [string]$VisionModel = "",
    [switch]$EnableSiliconFlowAudio,
    [string]$SiliconFlowApiKey = "",
    [string]$AsrModel = "FunAudioLLM/SenseVoiceSmall",
    [string]$TtsModel = "fishaudio/fish-speech-1.5",
    [string]$TtsVoice = "default",
    [switch]$SkipVerify
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")

$Profiles = @{
    "dashscope-hk" = @{
        BaseUrl = "https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1"
        Llm = "qwen-plus"
        Vision = "qwen-plus"
        Note = "Alibaba Cloud Model Studio Hong Kong OpenAI-compatible route."
    }
    "dashscope-cn" = @{
        BaseUrl = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        Llm = "qwen3.5-plus"
        Vision = "qwen3.5-plus"
        Note = "Alibaba Cloud Model Studio Beijing OpenAI-compatible route."
    }
    "siliconflow" = @{
        BaseUrl = "https://api.siliconflow.cn/v1"
        Llm = "Qwen/Qwen3-235B-A22B-Instruct-2507"
        Vision = "Qwen/Qwen2.5-VL-72B-Instruct"
        Note = "SiliconFlow OpenAI-compatible multimodal and audio route."
    }
    "volcengine" = @{
        BaseUrl = "https://ark.cn-beijing.volces.com/api/v3"
        Llm = ""
        Vision = ""
        Note = "Volcano Ark OpenAI-compatible route. Use your activated endpoint id as model."
    }
    "qianfan-aistudio" = @{
        BaseUrl = "https://aistudio.baidu.com/llm/lmapi/v3"
        Llm = "ernie-4.5-turbo-128k"
        Vision = "ernie-4.5-turbo-vl"
        Note = "Baidu AI Studio/Qianfan OpenAI-compatible LLM route."
    }
}

$Selected = $Profiles[$Profile]
if (-not $ApiKey) {
    throw "Provide -ApiKey for $Profile. The script does not write placeholder secrets into .env."
}

if (-not $LlmModel) {
    $LlmModel = $Selected.Llm
}
if (-not $VisionModel) {
    $VisionModel = $Selected.Vision
}
if (-not $LlmModel) {
    throw "Provide -LlmModel for $Profile. Some providers require an activated model or endpoint id."
}
if (-not $VisionModel) {
    $VisionModel = $LlmModel
}

$EnvPath = Join-Path $Root ".env"
$EnvExamplePath = Join-Path $Root ".env.example"
if (Test-Path $EnvPath) {
    Copy-Item $EnvPath (Join-Path $Root ".env.before-china-provider") -Force
}

$Values = @{
    "LLM_PROVIDER" = "openai_compatible"
    "VISION_PROVIDER" = "openai_compatible"
    "OPENAI_COMPATIBLE_BASE_URL" = $Selected.BaseUrl
    "OPENAI_COMPATIBLE_API_KEY" = $ApiKey
    "OPENAI_COMPATIBLE_LLM_MODEL" = $LlmModel
    "OPENAI_COMPATIBLE_VISION_MODEL" = $VisionModel
    "REALTIME_PROVIDER" = "none"
}

if ($EnableSiliconFlowAudio) {
    $AudioKey = $SiliconFlowApiKey
    if (-not $AudioKey -and $Profile -eq "siliconflow") {
        $AudioKey = $ApiKey
    }
    if (-not $AudioKey) {
        throw "Provide -SiliconFlowApiKey when -EnableSiliconFlowAudio is used with a non-SiliconFlow profile."
    }
    $Values["ASR_PROVIDER"] = "openai_compatible"
    $Values["TTS_PROVIDER"] = "openai_compatible"
    $Values["OPENAI_COMPATIBLE_ASR_BASE_URL"] = "https://api.siliconflow.cn/v1"
    $Values["OPENAI_COMPATIBLE_ASR_API_KEY"] = $AudioKey
    $Values["OPENAI_COMPATIBLE_ASR_MODEL"] = $AsrModel
    $Values["OPENAI_COMPATIBLE_ASR_ENDPOINT_PATH"] = "/audio/transcriptions"
    $Values["OPENAI_COMPATIBLE_TTS_BASE_URL"] = "https://api.siliconflow.cn/v1"
    $Values["OPENAI_COMPATIBLE_TTS_API_KEY"] = $AudioKey
    $Values["OPENAI_COMPATIBLE_TTS_MODEL"] = $TtsModel
    $Values["OPENAI_COMPATIBLE_TTS_VOICE"] = $TtsVoice
    $Values["OPENAI_COMPATIBLE_TTS_ENDPOINT_PATH"] = "/audio/speech"
    $Values["OPENAI_COMPATIBLE_TTS_RESPONSE_FORMAT"] = "mp3"
}

Set-DotEnvValues -Path $EnvPath -ExamplePath $EnvExamplePath -Values $Values

if ($SkipVerify) {
    Write-Host "China provider route written to .env for $Profile. Restart MODVII to apply it."
    Write-Host $Selected.Note
    exit 0
}

$Python = Join-Path $Root "apps\server\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = Resolve-Python
}
if (-not $Python) {
    throw "Python is required to verify the provider route."
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
        DialogueInput(messages=[ChatMessage(role="user", content="用一句中文回复：MODVII 国内供应商路线已连接。")])
    )
    print(f"provider={provider.provider_name}")
    print(f"model={provider.model}")
    print(f"text={result.text[:120]}")


asyncio.run(main())
'@

$TempScript = Join-Path $env:TEMP "modvii_verify_china_provider.py"
Set-Content -Path $TempScript -Value $VerifyScript -Encoding UTF8
Push-Location (Join-Path $Root "apps\server")
try {
    & $Python $TempScript
} finally {
    Pop-Location
    Remove-Item -Path $TempScript -Force -ErrorAction SilentlyContinue
}

Write-Host "China provider route verified for $Profile. Restart MODVII to apply it."
Write-Host $Selected.Note
