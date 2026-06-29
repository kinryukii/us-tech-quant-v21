param(
    [string]$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
)

$venvActivate = Join-Path $Root ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    . $venvActivate
}

$script = Join-Path $Root "scripts\v21\v21_092_r2_factor_filter_repair_and_weight_search_stability_tightening.py"
$test = Join-Path $Root "scripts\v21\test_v21_092_r2_factor_filter_repair_and_weight_search_stability_tightening.py"

python $script --root $Root
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python $test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "V21.092-R2 factor filter repair and stability tightening complete."
