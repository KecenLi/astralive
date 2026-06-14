$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

$Blocked = @(
    "README.md",
    "token",
    "gemini_key.txt",
    "api_key.txt",
    "codex_multi_agent_ai_visual_assistant_windows.md"
)

$AllowedDocs = @(
    "docs/cosyvoice3_setup.md",
    "docs/github_round_reminder.md"
)

Push-Location $Root
try {
    if (Get-Command git -ErrorAction SilentlyContinue) {
        $Tracked = git ls-files
    } else {
        $GitExe = Join-Path $env:ProgramFiles "Git\cmd\git.exe"
        if (-not (Test-Path $GitExe)) {
            throw "Git is required to run the public tree guard."
        }
        $Tracked = & $GitExe ls-files
    }
    foreach ($Path in $Tracked) {
        if (
            $Blocked -contains $Path -or
            $Path.EndsWith(".key") -or
            ($Path.StartsWith("docs/") -and -not ($AllowedDocs -contains $Path)) -or
            $Path.StartsWith("apps/web/public/live2d/")
        ) {
            throw "Blocked tracked path: $Path"
        }
    }
    Write-Host "Public tree guard passed."
} finally {
    Pop-Location
}
