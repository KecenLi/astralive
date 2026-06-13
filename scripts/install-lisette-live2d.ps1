param(
    [string]$ZipPath = ".installers\lisette-drive\lisette_v2.zip",
    [string]$OutputDir = "apps\web\public\live2d\lisette",
    [switch]$SetEnv,
    [switch]$AcceptNonCommercialTerms
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")

if (-not $AcceptNonCommercialTerms) {
    throw "Lisette is a third-party sample model for non-commercial local reference only. Rerun with -AcceptNonCommercialTerms after confirming the terms."
}

$ResolvedZip = if ([System.IO.Path]::IsPathRooted($ZipPath)) { $ZipPath } else { Join-Path $Root $ZipPath }
$ResolvedOutput = if ([System.IO.Path]::IsPathRooted($OutputDir)) { $OutputDir } else { Join-Path $Root $OutputDir }

if (-not (Test-Path $ResolvedZip)) {
    throw "Lisette zip not found: $ResolvedZip. Download lisette_v2.zip from ShiraLive2D/BOOTH/Google Drive and place it there."
}

if (Test-Path $ResolvedOutput) {
    Remove-Item -Path $ResolvedOutput -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $ResolvedOutput | Out-Null
Expand-Archive -Path $ResolvedZip -DestinationPath $ResolvedOutput -Force

$ModelJsonPath = Join-Path $ResolvedOutput "Lisette.model3.json"
if (-not (Test-Path $ModelJsonPath)) {
    throw "Lisette.model3.json was not found after extraction."
}

$Model = Get-Content -Path $ModelJsonPath -Raw | ConvertFrom-Json

$Expressions = @(
    @{ Name = "angry"; File = "Expressions/angry.exp3.json" },
    @{ Name = "frenzy"; File = "Expressions/frenzy.exp3.json" },
    @{ Name = "sad"; File = "Expressions/sad.exp3.json" },
    @{ Name = "sans_eye_glow"; File = "Expressions/sans_eye_glow.exp3.json" },
    @{ Name = "dark_mask"; File = "Expressions/dark_mask.exp3.json" },
    @{ Name = "dark_mask2"; File = "Expressions/dark_mask2.exp3.json" },
    @{ Name = "dark_mask3"; File = "Expressions/dark_mask3.exp3.json" },
    @{ Name = "dark_mask4"; File = "Expressions/dark_mask4.exp3.json" },
    @{ Name = "shy"; File = "Expressions/shy.exp3.json" },
    @{ Name = "tear"; File = "Expressions/tear.exp3.json" },
    @{ Name = "tongue_out"; File = "Expressions/tongue_out.exp3.json" },
    @{ Name = "body_X_reverse"; File = "Expressions/body_X_reverse.exp3.json" },
    @{ Name = "body_Y_reverse"; File = "Expressions/body_Y_reverse.exp3.json" },
    @{ Name = "body_Z_reverse"; File = "Expressions/body_Z_reverse.exp3.json" },
    @{ Name = "walking_toggle"; File = "Expressions/walking_toggle.exp3.json" }
)

$Motions = [ordered]@{
    Idle = @(
        @{ File = "Animations/breathing.motion3.json" },
        @{ File = "Animations/hand_fiddle_idle.motion3.json" },
        @{ File = "Animations/shy_idle.motion3.json" }
    )
    Breathing = @(@{ File = "Animations/breathing.motion3.json" })
    HandFiddle = @(@{ File = "Animations/hand_fiddle_idle.motion3.json" })
    ShyIdle = @(@{ File = "Animations/shy_idle.motion3.json" })
    Happy = @(@{ File = "Animations/happy_transition.motion3.json" })
    Greeting = @(@{ File = "Animations/hello_ani.motion3.json" })
    Angry = @(
        @{ File = "Animations/angry_face_expression.motion3.json" },
        @{ File = "Animations/angry_idle.motion3.json" }
    )
    Frenzy = @(
        @{ File = "Animations/frenzy_expression.motion3.json" },
        @{ File = "Animations/frenzy_idle.motion3.json" }
    )
    Sad = @(
        @{ File = "Animations/sad_expression.motion3.json" },
        @{ File = "Animations/sad_idle.motion3.json" }
    )
    SadIdle = @(@{ File = "Animations/sad_idle.motion3.json" })
    Jump = @(@{ File = "Animations/jump_ani.motion3.json" })
    Walk = @(@{ File = "Animations/walking_idle.motion3.json" })
    Run = @(@{ File = "Animations/run_idle.motion3.json" })
    FlingScissors = @(
        @{ File = "Animations/fling_scissors_intro.motion3.json" },
        @{ File = "Animations/fling_scissors.motion3.json" },
        @{ File = "Animations/fling_scissors_short.motion3.json" }
    )
    SansEyeGlow = @(@{ File = "Animations/sans_eye_glow_idle.motion3.json" })
}

$Model.FileReferences | Add-Member -NotePropertyName "Expressions" -NotePropertyValue $Expressions -Force
$Model.FileReferences | Add-Member -NotePropertyName "Motions" -NotePropertyValue $Motions -Force

foreach ($Group in $Model.Groups) {
    if ($Group.Name -eq "LipSync" -and (-not $Group.Ids -or $Group.Ids.Count -eq 0)) {
        $Group.Ids = @("ParamMouthOpenY")
    }
}

$ModelJson = $Model | ConvertTo-Json -Depth 20
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($ModelJsonPath, $ModelJson, $Utf8NoBom)

if ($SetEnv) {
    Set-DotEnvValues `
        -Path (Join-Path $Root ".env") `
        -ExamplePath (Join-Path $Root ".env.example") `
        -Values @{ "VITE_LIVE2D_MODEL_URL" = "./live2d/lisette/Lisette.model3.json" }
}

Write-Host "Lisette installed to $ResolvedOutput"
Write-Host "Model URL: ./live2d/lisette/Lisette.model3.json"
Write-Host "Scope: local non-commercial reference only; do not include the asset in public/commercial packages."
