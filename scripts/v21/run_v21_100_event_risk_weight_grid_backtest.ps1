param(
    [string]$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
)

$venvActivate = Join-Path $Root ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) { . $venvActivate }

$script = Join-Path $Root "scripts\v21\v21_100_event_risk_weight_grid_backtest.py"
$test = Join-Path $Root "scripts\v21\test_v21_100_event_risk_weight_grid_backtest.py"

python $script --root $Root
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python $test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
