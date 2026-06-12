$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")

Push-Location $Root
try {
    Invoke-Pnpm @("--filter", "@astralive/web", "build")
    Invoke-Pnpm @("--filter", "@astralive/web", "test")

    Push-Location "apps\server"
    try {
        $Uv = Resolve-Uv
        $Python = Resolve-Python

        if ($Uv) {
            & $Uv run pytest -s
            & $Uv run ruff check app
        } elseif ($Python) {
            & $Python -m pytest -s
            & $Python -m ruff check app
        } else {
            throw "Python 3.11+ or uv is required to run backend checks."
        }
    } finally {
        Pop-Location
    }
} finally {
    Pop-Location
}
