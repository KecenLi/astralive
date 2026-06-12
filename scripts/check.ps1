$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")

function Resolve-PnpmPackageScript {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PackagePrefix,
        [Parameter(Mandatory = $true)]
        [string]$RelativeScriptPath
    )

    $PnpmRoot = Join-Path $Root "node_modules\.pnpm"
    $Script = Get-ChildItem -Path $PnpmRoot -Directory -Filter "$PackagePrefix@*" |
        Sort-Object -Property Name -Descending |
        ForEach-Object { Join-Path $_.FullName $RelativeScriptPath } |
        Where-Object { Test-Path $_ } |
        Select-Object -First 1

    if (-not $Script) {
        throw "Could not find $PackagePrefix script at $RelativeScriptPath. Run pnpm install first."
    }
    return $Script
}

Push-Location $Root
try {
    Push-Location "apps\web"
    try {
        $Node = Resolve-CommandPath -Name "node.exe" -Candidates @(
            (Join-Path $env:ProgramFiles "nodejs\node.exe")
        )
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
