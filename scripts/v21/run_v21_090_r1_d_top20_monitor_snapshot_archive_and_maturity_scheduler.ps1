param(
    [string]$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
)

$venvActivate = Join-Path $Root ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    . $venvActivate
}

$script = Join-Path $Root "scripts\v21\v21_090_r1_d_top20_monitor_snapshot_archive_and_maturity_scheduler.py"
$test = Join-Path $Root "scripts\v21\test_v21_090_r1_d_top20_monitor_snapshot_archive_and_maturity_scheduler.py"

python $script --root $Root
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python $test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "V21.090-R1 D Top20 monitor archive and maturity scheduler complete."
