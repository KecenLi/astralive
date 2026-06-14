$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")

Push-Location (Join-Path $Root "apps\server")
try {
    $Uv = Resolve-Uv
    $Python = Resolve-Python

    if ($Uv) {
        Invoke-CmdExecutable -Executable $Uv -Arguments @(
            "run",
            "pyinstaller",
            "--noconfirm",
            "--clean",
            "--name",
            "modvii-server",
            "--distpath",
            "dist",
            "--workpath",
            "build",
            "--paths",
            ".",
            "--hidden-import",
            "google.genai",
            "--hidden-import",
            "google.genai.types",
            "--hidden-import",
            "google.auth",
            "--hidden-import",
            "google.auth.transport.requests",
            "--hidden-import",
            "certifi",
            "--hidden-import",
            "httpx",
            "--hidden-import",
            "httpcore",
            "--collect-data",
            "certifi",
            "--collect-data",
            "httpx",
            "modvii_server.py"
        )
    } elseif ($Python) {
        Invoke-CmdExecutable -Executable $Python -Arguments @(
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--name",
            "modvii-server",
            "--distpath",
            "dist",
            "--workpath",
            "build",
            "--paths",
            ".",
            "--hidden-import",
            "google.genai",
            "--hidden-import",
            "google.genai.types",
            "--hidden-import",
            "google.auth",
            "--hidden-import",
            "google.auth.transport.requests",
            "--hidden-import",
            "certifi",
            "--hidden-import",
            "httpx",
            "--hidden-import",
            "httpcore",
            "--collect-data",
            "certifi",
            "--collect-data",
            "httpx",
            "modvii_server.py"
        )
    } else {
        throw "Python 3.11+ or uv is required to package the MODVII backend."
    }
} finally {
    Pop-Location
}
