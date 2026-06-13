$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")

Push-Location $Root
try {
    Push-Location "apps\web"
    try {
        $Node = Resolve-Node
        if (-not $Node) {
            throw "Node.js is required to run frontend checks."
        }

        Invoke-CmdExecutable -Executable $Node -Arguments @(
            (Resolve-PnpmPackageScript -PackagePrefix "typescript" -RelativeScriptPath "node_modules\typescript\bin\tsc"),
            "-b"
        )
        Invoke-CmdExecutable -Executable $Node -Arguments @(
            (Resolve-PnpmPackageScript -PackagePrefix "vite" -RelativeScriptPath "node_modules\vite\bin\vite.js"),
            "build"
        )
        Invoke-CmdExecutable -Executable $Node -Arguments @(
            (Resolve-PnpmPackageScript -PackagePrefix "vitest" -RelativeScriptPath "node_modules\vitest\vitest.mjs"),
            "run"
        )
        Invoke-CmdExecutable -Executable $Node -Arguments @(
            (Resolve-PnpmPackageScript -PackagePrefix "eslint" -RelativeScriptPath "node_modules\eslint\bin\eslint.js"),
            "."
        )
    } finally {
        Pop-Location
    }

    Push-Location "apps\desktop"
    try {
        Invoke-NodePackageScript -PackagePrefix "typescript" -RelativeScriptPath "node_modules\typescript\bin\tsc" -Arguments @("-p", "tsconfig.json")
    } finally {
        Pop-Location
    }

    & (Join-Path $PSScriptRoot "verify-open-llm-vtuber-standards.ps1")
    & (Join-Path $PSScriptRoot "verify-modvii-adversarial-dialogue.ps1") -SkipDependencySync

    Push-Location "apps\server"
    try {
        $Uv = Resolve-Uv
        $Python = Resolve-Python

        if ($Uv) {
            Invoke-CmdExecutable -Executable $Uv -Arguments @("run", "python", "-m", "pytest", "-s")
            Invoke-CmdExecutable -Executable $Uv -Arguments @("run", "ruff", "check", "app")
        } elseif ($Python) {
            Invoke-CmdExecutable -Executable $Python -Arguments @("-m", "pytest", "-s")
            Invoke-CmdExecutable -Executable $Python -Arguments @("-m", "ruff", "check", "app")
        } else {
            throw "Python 3.11+ or uv is required to run backend checks."
        }
    } finally {
        Pop-Location
    }
} finally {
    Pop-Location
}
