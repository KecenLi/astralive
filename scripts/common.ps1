$ErrorActionPreference = "Stop"

function Resolve-CommandPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [string[]]$Candidates = @()
    )

    $Command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($Command) {
        return $Command.Source
    }

    foreach ($Candidate in $Candidates) {
        if ($Candidate -and (Test-Path $Candidate)) {
            return $Candidate
        }
    }

    return $null
}

function Get-UserPythonRoots {
    $PythonRoot = Join-Path $env:LOCALAPPDATA "Programs\Python"
    if (-not (Test-Path $PythonRoot)) {
        return @()
    }

    return Get-ChildItem -Path $PythonRoot -Directory -Filter "Python3*" |
        Sort-Object -Property Name -Descending |
        ForEach-Object { $_.FullName }
}

function Resolve-Python {
    $Candidates = @(Get-UserPythonRoots | ForEach-Object { Join-Path $_ "python.exe" })
    return Resolve-CommandPath -Name "python" -Candidates $Candidates
}

function Resolve-Uv {
    $Candidates = @()
    $Candidates += Get-UserPythonRoots | ForEach-Object { Join-Path $_ "Scripts\uv.exe" }
    $Candidates += Join-Path $env:USERPROFILE ".cargo\bin\uv.exe"
    return Resolve-CommandPath -Name "uv" -Candidates $Candidates
}

function Resolve-Ollama {
    $Candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
        (Join-Path $env:ProgramFiles "Ollama\ollama.exe")
    )
    return Resolve-CommandPath -Name "ollama" -Candidates $Candidates
}

function Resolve-Gcloud {
    $Candidates = @(
        (Join-Path $env:LOCALAPPDATA "Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"),
        (Join-Path $env:ProgramFiles "Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd")
    )
    if (${env:ProgramFiles(x86)}) {
        $Candidates += Join-Path ${env:ProgramFiles(x86)} "Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
    }
    return Resolve-CommandPath -Name "gcloud.cmd" -Candidates $Candidates
}

function Import-DotEnvFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path $Path)) {
        return
    }

    Get-Content -Path $Path | ForEach-Object {
        $Line = $_.Trim()
        if (-not $Line -or $Line.StartsWith("#") -or -not $Line.Contains("=")) {
            return
        }

        $Parts = $Line.Split("=", 2)
        $Name = $Parts[0].Trim()
        $Value = $Parts[1].Trim()
        if ($Name -and -not [Environment]::GetEnvironmentVariable($Name, "Process")) {
            [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
        }
    }
}

function Set-DotEnvValues {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [hashtable]$Values,
        [string]$ExamplePath = ""
    )

    if (-not (Test-Path $Path)) {
        if ($ExamplePath -and (Test-Path $ExamplePath)) {
            Copy-Item $ExamplePath $Path
        } else {
            New-Item -ItemType File -Path $Path -Force | Out-Null
        }
    }

    $Lines = @(Get-Content -Path $Path)
    $Seen = @{}

    for ($Index = 0; $Index -lt $Lines.Count; $Index++) {
        $Line = $Lines[$Index]
        if ($Line -notmatch "^\s*([^#][^=]*)=(.*)$") {
            continue
        }

        $Name = $Matches[1].Trim()
        if ($Values.ContainsKey($Name)) {
            $Lines[$Index] = "$Name=$($Values[$Name])"
            $Seen[$Name] = $true
        }
    }

    foreach ($Name in $Values.Keys) {
        if (-not $Seen.ContainsKey($Name)) {
            $Lines += "$Name=$($Values[$Name])"
        }
    }

    Set-Content -Path $Path -Value $Lines -Encoding UTF8
}

function ConvertTo-CmdArgument {
    param([string]$Argument)

    $Escaped = $Argument -replace '"', '\"'
    if ($Escaped -match '[\s&()^|<>"]') {
        return "`"$Escaped`""
    }
    return $Escaped
}

function Invoke-CmdExecutable {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [string[]]$Arguments = @()
    )

    $CommandLine = (ConvertTo-CmdArgument $Executable)
    if ($Arguments.Count -gt 0) {
        $CommandLine = "$CommandLine $((@($Arguments) | ForEach-Object { ConvertTo-CmdArgument $_ }) -join ' ')"
    }

    & cmd.exe /d /c $CommandLine
    if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "$Executable failed with exit code $LASTEXITCODE."
    }
}

function Invoke-Pnpm {
    param([string[]]$Arguments = @())

    $Pnpm = Resolve-CommandPath -Name "pnpm.cmd" -Candidates @(
        (Join-Path $env:ProgramFiles "nodejs\pnpm.cmd")
    )
    if ($Pnpm) {
        Invoke-CmdExecutable -Executable $Pnpm -Arguments $Arguments
        return
    }

    $Corepack = Join-Path $env:ProgramFiles "nodejs\corepack.cmd"
    if (Test-Path $Corepack) {
        Invoke-CmdExecutable -Executable $Corepack -Arguments (@("pnpm") + $Arguments)
        return
    }

    throw "pnpm is not available. Install Node.js LTS and run: corepack enable"
}
