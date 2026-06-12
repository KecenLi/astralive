$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

$Blocked = @(
    "README.md",
    "token",
    "codex_multi_agent_ai_visual_assistant_windows.md"
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
        if ($Blocked -contains $Path -or $Path.StartsWith("docs/") -or $Path.StartsWith("apps/web/public/live2d/")) {
            throw "Blocked tracked path: $Path"
        }
    }
    Write-Host "Public tree guard passed."
} finally {
    Pop-Location
}
