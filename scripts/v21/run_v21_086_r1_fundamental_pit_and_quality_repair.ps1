param(
    [string]$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
)

$venvActivate = Join-Path $Root ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    . $venvActivate
}

$audit = Join-Path $Root "scripts\v21\v21_086_r1_fundamental_pit_and_quality_repair.py"
$test = Join-Path $Root "scripts\v21\test_v21_086_r1_fundamental_pit_and_quality_repair.py"

python $audit --root $Root
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

python $test
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "V21.086-R1 fundamental PIT and quality repair complete."
