param(
    [string]$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
)

$venvActivate = Join-Path $Root ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    . $venvActivate
}

$script = Join-Path $Root "scripts\v21\v21_092_r3_factor_weight_effectiveness_marginal_contribution_and_risk_gate_calibration.py"
$test = Join-Path $Root "scripts\v21\test_v21_092_r3_factor_weight_effectiveness_marginal_contribution_and_risk_gate_calibration.py"

python $script --root $Root
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python $test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "V21.092-R3 factor weight effectiveness and risk gate calibration complete."
