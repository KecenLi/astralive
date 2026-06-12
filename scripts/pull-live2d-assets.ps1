param(
    [ValidateSet("hiyori_free")]
    [string]$Model = "hiyori_free",
    [ValidateSet("en", "ja", "zh", "ko")]
    [string]$Language = "en",
    [string]$OutputDir = "apps\web\public\live2d",
    [switch]$AcceptTerms
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Target = Join-Path $Root $OutputDir
$ZipDir = Join-Path $Root ".installers"
$ZipPath = Join-Path $ZipDir "$Model-$Language.zip"
$ExtractRoot = Join-Path $Target $Model

if (-not $AcceptTerms) {
    throw "Live2D sample assets require agreement to Live2D's Free Material License Agreement and sample data terms. Rerun with -AcceptTerms after confirming the license."
}

New-Item -ItemType Directory -Force -Path $Target | Out-Null
New-Item -ItemType Directory -Force -Path $ZipDir | Out-Null

$Downloads = @{
    hiyori_free = @{
        en = "https://cubism.live2d.com/sample-data/bin/hiyori_free/hiyori_free_en.zip"
        ja = "https://cubism.live2d.com/sample-data/bin/hiyori_free/hiyori_free_jp.zip"
        zh = "https://cubism.live2d.com/sample-data/bin/hiyori_free/hiyori_free_zh.zip"
        ko = "https://cubism.live2d.com/sample-data/bin/hiyori_free/hiyori_free_ko.zip"
    }
}

$Url = $Downloads[$Model][$Language]
Write-Host "Downloading $Model ($Language) from Live2D official sample data..."
Invoke-WebRequest -Uri $Url -OutFile $ZipPath -UseBasicParsing

if (Test-Path $ExtractRoot) {
    Remove-Item -Path $ExtractRoot -Recurse -Force
}

Expand-Archive -Path $ZipPath -DestinationPath $ExtractRoot -Force

$ModelJson = Get-ChildItem -Path $ExtractRoot -Filter "*.model3.json" -Recurse |
    Select-Object -First 1

if (-not $ModelJson) {
    throw "Downloaded archive did not contain a model3.json file."
}

$Relative = $ModelJson.FullName.Substring($Target.Length).TrimStart("\") -replace "\\", "/"
Write-Host "Live2D model installed under $OutputDir."
Write-Host "Set VITE_LIVE2D_MODEL_URL=/live2d/$Relative in .env."
