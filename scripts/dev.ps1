param(
    [ValidateSet("server", "web", "all")]
    [string]$Target = "all"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")
Import-DotEnvFile -Path (Join-Path $Root ".env")

function Start-Server {
    Push-Location (Join-Path $Root "apps\server")
    try {
        $Uv = Resolve-Uv
        $Python = Resolve-Python
        $ServerHost = if ($env:SERVER_HOST) { $env:SERVER_HOST } else { "127.0.0.1" }
        $ServerPort = if ($env:SERVER_PORT) { $env:SERVER_PORT } else { "8000" }

        if ($Uv) {
            Invoke-CmdExecutable -Executable $Uv -Arguments @(
                "run", "uvicorn", "app.main:app", "--host", $ServerHost, "--port", $ServerPort, "--reload"
            )
        } elseif ($Python) {
            Invoke-CmdExecutable -Executable $Python -Arguments @(
                "-m", "uvicorn", "app.main:app", "--host", $ServerHost, "--port", $ServerPort, "--reload"
            )
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
        Invoke-Pnpm @("--filter", "@astralive/web", "dev")
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
