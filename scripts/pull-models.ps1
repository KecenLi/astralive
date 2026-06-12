param(
    [string]$Model = "qwen2.5:0.5b"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    throw "Ollama is not installed. Install Ollama for Windows, then rerun this script."
}

ollama pull $Model
Write-Host "Pulled $Model. Set LLM_PROVIDER=ollama and OLLAMA_LLM_MODEL=$Model in .env to use it."

