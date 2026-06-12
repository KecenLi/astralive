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
} finally {
    Pop-Location
}
