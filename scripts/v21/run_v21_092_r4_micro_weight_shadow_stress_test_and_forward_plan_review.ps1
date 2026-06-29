param(
    [string]$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
)

$venvActivate = Join-Path $Root ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    . $venvActivate
}

$script = Join-Path $Root "scripts\v21\v21_092_r4_micro_weight_shadow_stress_test_and_forward_plan_review.py"
$test = Join-Path $Root "scripts\v21\test_v21_092_r4_micro_weight_shadow_stress_test_and_forward_plan_review.py"

python $script --root $Root
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python $test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "V21.092-R4 micro-weight shadow stress test complete."
