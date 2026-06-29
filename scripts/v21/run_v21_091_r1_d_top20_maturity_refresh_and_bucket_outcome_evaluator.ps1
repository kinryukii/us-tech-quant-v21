param(
    [string]$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
)

$venvActivate = Join-Path $Root ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    . $venvActivate
}

$script = Join-Path $Root "scripts\v21\v21_091_r1_d_top20_maturity_refresh_and_bucket_outcome_evaluator.py"
$test = Join-Path $Root "scripts\v21\test_v21_091_r1_d_top20_maturity_refresh_and_bucket_outcome_evaluator.py"

python $script --root $Root
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python $test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "V21.091-R1 D Top20 maturity refresh and bucket outcome evaluator complete."
