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
    $Candidates += Join-Path $env:USERPROFILE ".local\bin\uv.exe"
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

function Add-ProcessPathEntry {
    param([string]$Path)

    if (-not $Path -or -not (Test-Path $Path)) {
        return
    }

    $Entries = @($env:Path -split [System.IO.Path]::PathSeparator)
    if ($Entries -notcontains $Path) {
        $env:Path = "$Path$([System.IO.Path]::PathSeparator)$env:Path"
    }
}

function Get-ProjectRoot {
    return Split-Path -Parent $PSScriptRoot
}

function Get-ApiHoldPath {
    param([string]$Provider = "vertex-ai")

    return Join-Path (Join-Path (Get-ProjectRoot) "data\api-hold") "$Provider.json"
}

function Test-QuotaExhaustedText {
    param([string]$Text)

    return $Text -match "RESOURCE_EXHAUSTED" -or
        $Text -match "Resource exhausted" -or
        $Text -match "HTTP 429" -or
        $Text -match '"code"\s*:\s*429'
}

function Set-ApiHold {
    param(
        [string]$Provider = "vertex-ai",
        [string]$Reason = "API quota or rate limit was exhausted.",
        [string]$Detail = "",
        [string]$Command = ""
    )

    $HoldPath = Get-ApiHoldPath -Provider $Provider
    New-Item -ItemType Directory -Path (Split-Path -Parent $HoldPath) -Force | Out-Null
    [ordered]@{
        provider = $Provider
        reason = $Reason
        detail = $Detail
        command = $Command
        created_at = (Get-Date).ToUniversalTime().ToString("o")
        recovery = "Delete this local file after quota/rate limits recover, then rerun the verifier."
    } | ConvertTo-Json -Depth 4 | Set-Content -Path $HoldPath -Encoding UTF8
}

function Assert-ApiHoldClear {
    param([string]$Provider = "vertex-ai")

    $HoldPath = Get-ApiHoldPath -Provider $Provider
    if (-not (Test-Path $HoldPath)) {
        return
    }

    $Reason = "API verification is paused because a previous run hit quota or rate limits."
    try {
        $Hold = Get-Content -Path $HoldPath -Raw | ConvertFrom-Json
        if ($Hold.reason) {
            $Reason = $Hold.reason
        }
    } catch {
        # Keep the default reason if the local marker is not parseable.
    }

    throw "$Reason`nHold marker: $HoldPath`nDelete this local marker only after quota/rate limits recover."
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

    Add-ProcessPathEntry -Path (Join-Path $env:ProgramFiles "nodejs")

    $Extension = [System.IO.Path]::GetExtension($Executable).ToLowerInvariant()
    if ($Extension -in @(".cmd", ".bat")) {
        $CommandLine = (ConvertTo-CmdArgument $Executable)
        if ($Arguments.Count -gt 0) {
            $CommandLine = "$CommandLine $((@($Arguments) | ForEach-Object { ConvertTo-CmdArgument $_ }) -join ' ')"
        }
        $Process = Start-Process -FilePath "cmd.exe" -ArgumentList @("/d", "/c", $CommandLine) -NoNewWindow -Wait -PassThru
    } else {
        $ArgumentLine = (@($Arguments) | ForEach-Object { ConvertTo-CmdArgument $_ }) -join " "
        $Process = Start-Process -FilePath $Executable -ArgumentList $ArgumentLine -NoNewWindow -Wait -PassThru
    }
    if ($Process.ExitCode -ne 0) {
        throw "$Executable failed with exit code $($Process.ExitCode)."
    }
}

function Invoke-ApiCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [string[]]$Arguments = @(),
        [string]$Provider = "vertex-ai",
        [string]$CommandName = "API verifier"
    )

    Assert-ApiHoldClear -Provider $Provider
    Add-ProcessPathEntry -Path (Join-Path $env:ProgramFiles "nodejs")

    $StdOut = Join-Path $env:TEMP "astralive_api_stdout_$([guid]::NewGuid().ToString('N')).log"
    $StdErr = Join-Path $env:TEMP "astralive_api_stderr_$([guid]::NewGuid().ToString('N')).log"
    try {
        $Extension = [System.IO.Path]::GetExtension($Executable).ToLowerInvariant()
        if ($Extension -in @(".cmd", ".bat")) {
            $CommandLine = (ConvertTo-CmdArgument $Executable)
            if ($Arguments.Count -gt 0) {
                $CommandLine = "$CommandLine $((@($Arguments) | ForEach-Object { ConvertTo-CmdArgument $_ }) -join ' ')"
            }
            $Process = Start-Process -FilePath "cmd.exe" -ArgumentList @("/d", "/c", $CommandLine) -NoNewWindow -Wait -PassThru -RedirectStandardOutput $StdOut -RedirectStandardError $StdErr
        } else {
            $ArgumentLine = (@($Arguments) | ForEach-Object { ConvertTo-CmdArgument $_ }) -join " "
            $Process = Start-Process -FilePath $Executable -ArgumentList $ArgumentLine -NoNewWindow -Wait -PassThru -RedirectStandardOutput $StdOut -RedirectStandardError $StdErr
        }

        $Output = if (Test-Path $StdOut) { Get-Content -Path $StdOut -Raw } else { "" }
        $ErrorOutput = if (Test-Path $StdErr) { Get-Content -Path $StdErr -Raw } else { "" }
        $Combined = "$Output`n$ErrorOutput"
        if ($Output) {
            Write-Host $Output.TrimEnd()
        }
        if ($ErrorOutput) {
            Write-Error $ErrorOutput.TrimEnd() -ErrorAction Continue
        }

        if ($Process.ExitCode -ne 0) {
            if (Test-QuotaExhaustedText -Text $Combined) {
                Set-ApiHold -Provider $Provider -Reason "$Provider quota or rate limit was exhausted." -Detail $Combined -Command $CommandName
            }
            throw "$Executable failed with exit code $($Process.ExitCode)."
        }

        if (Test-QuotaExhaustedText -Text $Combined) {
            Set-ApiHold -Provider $Provider -Reason "$Provider quota or rate limit was exhausted." -Detail $Combined -Command $CommandName
            throw "$CommandName returned quota exhaustion output."
        }
    } finally {
        Remove-Item -Path $StdOut, $StdErr -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-Pnpm {
    param([string[]]$Arguments = @())

    $PreviousShell = [Environment]::GetEnvironmentVariable("SHELL", "Process")
    Remove-Item Env:SHELL -ErrorAction SilentlyContinue
    try {
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
    } finally {
        if ($null -ne $PreviousShell) {
            [Environment]::SetEnvironmentVariable("SHELL", $PreviousShell, "Process")
        }
    }
}
