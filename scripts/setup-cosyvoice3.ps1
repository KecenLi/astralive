param(
    [string]$RepoDir = "",
    [string]$ModelDir = "",
    [string]$TorchIndexUrl = "",
    [switch]$SkipRepoClone,
    [switch]$SkipDependencyInstall,
    [switch]$SkipModelDownload,
    [switch]$InstallTtsfrd,
    [switch]$SkipWhisper,
    [switch]$NoEnvWrite
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$ProjectRoot = Get-ProjectRoot
if (-not $RepoDir) {
    $RepoDir = Join-Path $ProjectRoot "third_party\CosyVoice"
}
if (-not $ModelDir) {
    $ModelDir = Join-Path $ProjectRoot "models\Fun-CosyVoice3-0.5B"
}

function Resolve-Python310 {
    $Uv = Resolve-Uv
    if ($Uv) {
        Invoke-External -FilePath $Uv -Arguments @("python", "install", "3.10")
        return @{ Kind = "uv"; Command = $Uv }
    }

    $Py = Resolve-CommandPath -Name "py.exe" -Candidates @((Join-Path $env:windir "py.exe"))
    if ($Py) {
        & $Py -3.10 --version *> $null
        if ($LASTEXITCODE -eq 0) {
            return @{ Kind = "py"; Command = $Py }
        }
    }

    throw "Python 3.10 was not found. Install Python 3.10 for Windows or install uv, then rerun this script."
}

function New-CosyVoiceVenv {
    param([hashtable]$Python310, [string]$VenvPath)

    if (Test-Path (Join-Path $VenvPath "Scripts\python.exe")) {
        return Join-Path $VenvPath "Scripts\python.exe"
    }

    New-Item -ItemType Directory -Path (Split-Path -Parent $VenvPath) -Force | Out-Null
    if ($Python310.Kind -eq "uv") {
        Invoke-External -FilePath $Python310.Command -Arguments @("venv", "--seed", "--python", "3.10", $VenvPath)
    } else {
        Invoke-External -FilePath $Python310.Command -Arguments @("-3.10", "-m", "venv", $VenvPath)
    }
    return Join-Path $VenvPath "Scripts\python.exe"
}

function Resolve-GitForWindows {
    $Candidates = @(
        (Join-Path $env:ProgramFiles "Git\cmd\git.exe"),
        (Join-Path $env:ProgramFiles "Git\bin\git.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Git\cmd\git.exe")
    )
    if (${env:ProgramFiles(x86)}) {
        $Candidates += Join-Path ${env:ProgramFiles(x86)} "Git\cmd\git.exe"
    }
    return Resolve-CommandPath -Name "git.exe" -Candidates $Candidates
}

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $ArgumentLine = ($Arguments | ForEach-Object { ConvertTo-CmdArgument $_ }) -join " "
    $Process = Start-Process -FilePath $FilePath -ArgumentList $ArgumentLine -NoNewWindow -Wait -PassThru
    if ($Process.ExitCode -ne 0) {
        throw "$FilePath failed with exit code $($Process.ExitCode): $ArgumentLine"
    }
}

function Install-GitHubZip {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    $TempRoot = Join-Path $env:TEMP ("modvii-zip-" + [Guid]::NewGuid().ToString("n"))
    $ZipPath = Join-Path $TempRoot "source.zip"
    $ExtractPath = Join-Path $TempRoot "extract"
    New-Item -ItemType Directory -Path $TempRoot, $ExtractPath -Force | Out-Null
    try {
        Invoke-WebRequest -Uri $Url -OutFile $ZipPath
        Expand-Archive -Path $ZipPath -DestinationPath $ExtractPath -Force
        $Expanded = Get-ChildItem -Path $ExtractPath -Directory | Select-Object -First 1
        if (-not $Expanded) {
            throw "Archive did not contain a source directory: $Url"
        }
        New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
        if (Test-Path $Destination) {
            Remove-Item -Path $Destination -Recurse -Force
        }
        Move-Item -Path $Expanded.FullName -Destination $Destination
    } finally {
        Remove-Item -Path $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if (-not $SkipRepoClone) {
    $Git = Resolve-GitForWindows
    if (-not (Test-Path $RepoDir)) {
        if ($Git) {
            Invoke-External -FilePath $Git -Arguments @("clone", "--recursive", "https://github.com/FunAudioLLM/CosyVoice.git", $RepoDir)
        } else {
            Write-Host "Git for Windows was not found. Downloading CosyVoice source ZIP instead."
            Install-GitHubZip -Url "https://github.com/FunAudioLLM/CosyVoice/archive/refs/heads/main.zip" -Destination $RepoDir
            Install-GitHubZip -Url "https://github.com/shivammehta25/Matcha-TTS/archive/refs/heads/main.zip" -Destination (Join-Path $RepoDir "third_party\Matcha-TTS")
        }
    } else {
        if ($Git) {
            Invoke-External -FilePath $Git -Arguments @("-C", $RepoDir, "submodule", "update", "--init", "--recursive")
        } elseif (-not (Test-Path (Join-Path $RepoDir "third_party\Matcha-TTS"))) {
            Install-GitHubZip -Url "https://github.com/shivammehta25/Matcha-TTS/archive/refs/heads/main.zip" -Destination (Join-Path $RepoDir "third_party\Matcha-TTS")
        } else {
            Write-Host "Git for Windows was not found. Keeping existing CosyVoice source tree."
        }
    }
}

$Python310 = Resolve-Python310
$VenvPath = Join-Path $RepoDir ".venv"
$Python = New-CosyVoiceVenv -Python310 $Python310 -VenvPath $VenvPath

if (-not $SkipDependencyInstall) {
    try {
        Invoke-External -FilePath $Python -Arguments @("-m", "pip", "--version")
    } catch {
        Invoke-External -FilePath $Python -Arguments @("-m", "ensurepip", "--upgrade")
    }
    Invoke-External -FilePath $Python -Arguments @("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel")
    if ($TorchIndexUrl) {
        Invoke-External -FilePath $Python -Arguments @("-m", "pip", "install", "torch", "torchaudio", "--index-url", $TorchIndexUrl)
    }
    $RequirementsPath = Join-Path $env:TEMP "modvii-cosyvoice3-requirements.txt"
    Get-Content -Path (Join-Path $RepoDir "requirements.txt") |
        Where-Object { $_ -notmatch "^\s*openai-whisper==" } |
        Set-Content -Path $RequirementsPath -Encoding UTF8
    Invoke-External -FilePath $Python -Arguments @("-m", "pip", "install", "-r", $RequirementsPath)
    if (-not $SkipWhisper) {
        Invoke-External -FilePath $Python -Arguments @("-m", "pip", "install", "setuptools<81")
        Invoke-External -FilePath $Python -Arguments @("-m", "pip", "install", "--no-build-isolation", "openai-whisper==20231117")
        Invoke-External -FilePath $Python -Arguments @("-m", "pip", "install", "imageio-ffmpeg")
    }
    Invoke-External -FilePath $Python -Arguments @("-m", "pip", "install", "huggingface_hub")
}

if (-not $SkipModelDownload) {
    New-Item -ItemType Directory -Path $ModelDir -Force | Out-Null
    $DownloadScript = Join-Path $env:TEMP "modvii-download-cosyvoice3.py"
    @"
from huggingface_hub import snapshot_download
snapshot_download("FunAudioLLM/Fun-CosyVoice3-0.5B-2512", local_dir=r"$ModelDir")
"@ | Set-Content -Path $DownloadScript -Encoding UTF8
    Invoke-External -FilePath $Python -Arguments @($DownloadScript)
    Remove-Item $DownloadScript -Force -ErrorAction SilentlyContinue
}

if ($InstallTtsfrd) {
    $TtsfrdDir = Join-Path $ProjectRoot "models\CosyVoice-ttsfrd"
    New-Item -ItemType Directory -Path $TtsfrdDir -Force | Out-Null
    $DownloadTtsfrdScript = Join-Path $env:TEMP "modvii-download-cosyvoice-ttsfrd.py"
    @"
from huggingface_hub import snapshot_download
snapshot_download("FunAudioLLM/CosyVoice-ttsfrd", local_dir=r"$TtsfrdDir")
"@ | Set-Content -Path $DownloadTtsfrdScript -Encoding UTF8
    Invoke-External -FilePath $Python -Arguments @($DownloadTtsfrdScript)
    Remove-Item $DownloadTtsfrdScript -Force -ErrorAction SilentlyContinue
    Write-Host "CosyVoice-ttsfrd downloaded to $TtsfrdDir. Its Linux wheel is optional; Windows will use wetext if ttsfrd is unavailable."
}

if (-not $NoEnvWrite) {
    $EnvPath = Join-Path $ProjectRoot ".env"
    $ExamplePath = Join-Path $ProjectRoot ".env.example"
    Set-DotEnvValues -Path $EnvPath -ExamplePath $ExamplePath -Values @{
        "TTS_PROVIDER" = "cosyvoice3"
        "ASR_PROVIDER" = "local_whisper"
        "REALTIME_PROVIDER" = "none"
        "LOCAL_ASR_PYTHON" = $Python
        "LOCAL_ASR_WORKER_SCRIPT" = (Join-Path $ProjectRoot "scripts\local_whisper_worker.py")
        "LOCAL_ASR_MODEL" = "base"
        "LOCAL_ASR_DEVICE" = "cpu"
        "LOCAL_ASR_TIMEOUT_SECONDS" = "120"
        "AUDIO_PREWARM_ENABLED" = "true"
        "COSYVOICE3_PYTHON" = $Python
        "COSYVOICE3_REPO_DIR" = $RepoDir
        "COSYVOICE3_MODEL_DIR" = $ModelDir
        "COSYVOICE3_SCRIPT" = (Join-Path $ProjectRoot "scripts\cosyvoice3_synth.py")
        "COSYVOICE3_WORKER_ENABLED" = "true"
        "COSYVOICE3_WORKER_SCRIPT" = (Join-Path $ProjectRoot "scripts\cosyvoice3_worker.py")
        "COSYVOICE3_SEED" = "7327"
        "COSYVOICE3_PROMPT_AUDIO" = (Join-Path $RepoDir "asset\zero_shot_prompt.wav")
        "COSYVOICE3_DEVICE" = "cpu"
        "COSYVOICE3_TIMEOUT_SECONDS" = "120"
    }
}

Write-Host "CosyVoice3 is ready."
Write-Host "Python: $Python"
Write-Host "Repo:   $RepoDir"
Write-Host "Model:  $ModelDir"
Write-Host "Run scripts\verify-vertex-tts.ps1 for cloud TTS or send a text turn with TTS_PROVIDER=cosyvoice3 to test local synthesis."
