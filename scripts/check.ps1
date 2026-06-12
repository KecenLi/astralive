$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

function Invoke-Pnpm {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

    if (Get-Command pnpm -ErrorAction SilentlyContinue) {
        pnpm @Arguments
        return
    }

    $Corepack = Join-Path $env:ProgramFiles "nodejs\corepack.cmd"
    if (Test-Path $Corepack) {
        & $Corepack pnpm @Arguments
        return
    }

    throw "pnpm is not available. Install Node.js LTS and run: corepack enable"
}

Push-Location $Root
try {
    Invoke-Pnpm --filter "@astralive/web" build
    Invoke-Pnpm --filter "@astralive/web" test

    Push-Location "apps\server"
    try {
        if (Get-Command uv -ErrorAction SilentlyContinue) {
            uv run pytest
            uv run ruff check app
        } elseif (Get-Command python -ErrorAction SilentlyContinue) {
            python -m pytest
            python -m ruff check app
        } else {
            throw "Python 3.11+ or uv is required to run backend checks."
        }
    } finally {
        Pop-Location
    }
} finally {
    Pop-Location
}
