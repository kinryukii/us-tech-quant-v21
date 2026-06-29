param(
    [string]$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
)

$venvActivate = Join-Path $Root ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    . $venvActivate
}

$script = Join-Path $Root "scripts\v21\v21_089_r1_d_top20_bucket_monitor_and_low_quality_momentum_review.py"
$test = Join-Path $Root "scripts\v21\test_v21_089_r1_d_top20_bucket_monitor_and_low_quality_momentum_review.py"

python $script --root $Root
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python $test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "V21.089-R1 D Top20 bucket monitor and low-quality momentum review complete."
