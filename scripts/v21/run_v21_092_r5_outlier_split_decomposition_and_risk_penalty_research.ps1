param(
    [string]$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
)

$venvActivate = Join-Path $Root ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) { . $venvActivate }

$script = Join-Path $Root "scripts\v21\v21_092_r5_outlier_split_decomposition_and_risk_penalty_research.py"
$test = Join-Path $Root "scripts\v21\test_v21_092_r5_outlier_split_decomposition_and_risk_penalty_research.py"

python $script --root $Root
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python $test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "V21.092-R5 outlier decomposition and risk penalty research complete."
