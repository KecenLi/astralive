param(
    [switch]$SkipLive2D
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")

Push-Location $Root
try {
    if (-not $SkipLive2D) {
        & (Join-Path $PSScriptRoot "pull-live2d-assets.ps1") -Model haru -Language en -AcceptTerms
    }

    Push-Location "apps\web"
    try {
        Invoke-NodePackageScript -PackagePrefix "typescript" -RelativeScriptPath "node_modules\typescript\bin\tsc" -Arguments @("-b")
        Invoke-NodePackageScript -PackagePrefix "vite" -RelativeScriptPath "node_modules\vite\bin\vite.js" -Arguments @("build")
    } finally {
        Pop-Location
    }

    & (Join-Path $PSScriptRoot "build-server-exe.ps1")

    Push-Location "apps\desktop"
    try {
        $env:CSC_IDENTITY_AUTO_DISCOVERY = "false"
        Invoke-NodePackageScript -PackagePrefix "typescript" -RelativeScriptPath "node_modules\typescript\bin\tsc" -Arguments @("-p", "tsconfig.json")
        Invoke-NodePackageScript -PackagePrefix "electron-builder" -RelativeScriptPath "node_modules\electron-builder\cli.js" -Arguments @("--win", "nsis", "portable")
    } finally {
        Remove-Item Env:CSC_IDENTITY_AUTO_DISCOVERY -ErrorAction SilentlyContinue
        Pop-Location
    }
} finally {
    Pop-Location
}
