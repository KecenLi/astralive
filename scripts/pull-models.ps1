param(
    [string]$Model = "qwen2.5:0.5b"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$Ollama = Resolve-Ollama
if (-not $Ollama) {
    throw "Ollama is not installed. Install Ollama for Windows, then rerun this script."
}

& $Ollama pull $Model
Write-Host "Pulled $Model. Set LLM_PROVIDER=ollama and OLLAMA_LLM_MODEL=$Model in .env to use it."
