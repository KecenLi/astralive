$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")

Push-Location $Root
try {
    Invoke-Pnpm @("--filter", "@astralive/web", "build")
} finally {
    Pop-Location
}
