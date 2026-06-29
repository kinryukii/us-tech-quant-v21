param(
    [string]$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
)

$venvActivate = Join-Path $Root ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    . $venvActivate
}

$script = Join-Path $Root "scripts\v21\v21_092_r1_factor_effectiveness_nested_walkforward_and_dynamic_weight_shadow_search.py"
$test = Join-Path $Root "scripts\v21\test_v21_092_r1_factor_effectiveness_nested_walkforward_and_dynamic_weight_shadow_search.py"

python $script --root $Root
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python $test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "V21.092-R1 factor effectiveness and dynamic weight shadow search complete."
