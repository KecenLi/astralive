$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$ReportPath = Join-Path $LogDir "open-llm-vtuber-parity-$((Get-Date).ToString('yyyyMMdd-HHmmss')).md"

function Test-Text {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Pattern
    )
    if (-not (Test-Path (Join-Path $Root $Path))) {
        return $false
    }
    return Select-String -Path (Join-Path $Root $Path) -Pattern $Pattern -Quiet
}

$Checks = @(
    @{ name = "Electron desktop shell"; ok = Test-Path (Join-Path $Root "apps\desktop\src\main.ts"); risk = "exe packaging is impossible without desktop shell." },
    @{ name = "Preload IPC boundary"; ok = Test-Text "apps\desktop\src\preload.ts" "contextBridge"; risk = "renderer would need unsafe Node access." },
    @{ name = "Desktop screen source"; ok = Test-Text "apps\desktop\src\main.ts" "desktopCapturer"; risk = "screen capture cannot match Open-LLM-VTuber desktop behavior." },
    @{ name = "Media permission handler"; ok = Test-Text "apps\desktop\src\main.ts" "setPermissionRequestHandler"; risk = "first-run permissions would remain browser-only." },
    @{ name = "Autostart toggle"; ok = Test-Text "apps\desktop\src\main.ts" "setLoginItemSettings"; risk = "boot autostart option missing." },
    @{ name = "Low-fps screen mode"; ok = Test-Text "apps\web\src\features\media\frameSampler.ts" "low_fps"; risk = "cost-stable visual mode missing." },
    @{ name = "Continuous sampled video mode"; ok = Test-Text "apps\web\src\features\media\frameSampler.ts" "continuous"; risk = "continuous visual mode missing." },
    @{ name = "Camera and screen panels"; ok = ((Test-Path (Join-Path $Root "apps\web\src\components\CameraPanel\CameraPanel.tsx")) -and (Test-Path (Join-Path $Root "apps\web\src\components\ScreenCapturePanel\ScreenCapturePanel.tsx"))); risk = "visual perception UI incomplete." },
    @{ name = "Wake word configured"; ok = ((Test-Text ".env.example" "WAKE_WORD=") -and (Test-Text "apps\web\src\features\wakeword\wakePhrase.ts" "wakeWord")); risk = "keyword flow does not match MODVII." },
    @{ name = "Wake plus request extraction"; ok = Test-Text "apps\web\src\features\wakeword\wakePhrase.ts" "extractWakeRequest"; risk = "speaker request after wake word can be lost." },
    @{ name = "Poor microphone constraints"; ok = Test-Text "apps\web\src\components\MicPanel\MicPanel.tsx" "noiseSuppression"; risk = "bad microphone input remains fragile." },
    @{ name = "Live2D Haru default"; ok = Test-Text "apps\web\src\lib\env.ts" "haru.model3.json"; risk = "default Live2D model missing." },
    @{ name = "Live2D expression mapping"; ok = Test-Text "apps\web\src\features\avatar\avatarController.ts" "expressionName"; risk = "avatar cannot reflect assistant state." },
    @{ name = "Local license references"; ok = Test-Path (Join-Path $Root "README.md"); risk = "reference and license notes missing locally." },
    @{ name = "Installer and portable target"; ok = Test-Text "apps\desktop\package.json" "portable"; risk = "portable exe target missing." }
)

$Failed = @($Checks | Where-Object { -not $_.ok })
$Lines = @()
$Lines += "# MODVII vs Open-LLM-VTuber Parity Report"
$Lines += ""
$Lines += "Generated: $((Get-Date).ToUniversalTime().ToString('o'))"
$Lines += ""
$Lines += "Reference: https://github.com/Open-LLM-VTuber/Open-LLM-VTuber"
$Lines += ""
$Lines += "## Checks"
$Lines += ""
foreach ($Check in $Checks) {
    $Mark = if ($Check.ok) { "[x]" } else { "[ ]" }
    $Lines += "- $Mark $($Check.name)"
    if (-not $Check.ok) {
        $Lines += "  Risk: $($Check.risk)"
    }
}
$Lines += ""
$Lines += "## Known Risk Areas"
$Lines += ""
$Lines += "- Live2D sample assets are locally ignored and must be pulled before package builds."
$Lines += "- Lisette remains non-commercial reference only and must not be bundled by default."
$Lines += "- Continuous video is sampled upload, not raw 30 fps streaming."
$Lines += "- GUI permission behavior must still be confirmed on real Windows desktop hardware."

Set-Content -Path $ReportPath -Value $Lines -Encoding UTF8
Write-Host "Open-LLM-VTuber parity report: $ReportPath"
if ($Failed.Count -gt 0) {
    throw "$($Failed.Count) parity check(s) failed. See report for details."
}
