param(
    [ValidateSet("server", "web", "all")]
    [string]$Target = "all"
)

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

function Start-Server {
    Push-Location (Join-Path $Root "apps\server")
    try {
        if (Get-Command uv -ErrorAction SilentlyContinue) {
            uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
        } elseif (Get-Command python -ErrorAction SilentlyContinue) {
            python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
        } else {
            throw "Python 3.11+ or uv is required to start the server."
        }
    } finally {
        Pop-Location
    }
}

function Start-Web {
    Push-Location $Root
    try {
        Invoke-Pnpm --filter "@astralive/web" dev
    } finally {
        Pop-Location
    }
}

switch ($Target) {
    "server" {
        Start-Server
    }
    "web" {
        Start-Web
    }
    "all" {
        Start-Process powershell -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSScriptRoot\dev.ps1`"", "server" -WorkingDirectory $Root
        Start-Process powershell -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSScriptRoot\dev.ps1`"", "web" -WorkingDirectory $Root
        Start-Process "http://localhost:5173"
    }
}
