$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")

Push-Location $Root
try {
    Push-Location "apps\web"
    try {
        Invoke-NodePackageScript -PackagePrefix "typescript" -RelativeScriptPath "node_modules\typescript\bin\tsc" -Arguments @("-b")
        Invoke-NodePackageScript -PackagePrefix "vite" -RelativeScriptPath "node_modules\vite\bin\vite.js" -Arguments @("build")
    } finally {
        Pop-Location
    }
} finally {
    Pop-Location
}
