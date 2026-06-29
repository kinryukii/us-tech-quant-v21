param(
    [string]$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
)

$venvActivate = Join-Path $Root ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    . $venvActivate
}

$script = Join-Path $Root "scripts\v21\v21_088_r1_interaction_maturity_recheck_and_pullback_repair_review.py"
$test = Join-Path $Root "scripts\v21\test_v21_088_r1_interaction_maturity_recheck_and_pullback_repair_review.py"

python $script --root $Root
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python $test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "V21.088-R1 interaction maturity recheck and pullback repair review complete."
