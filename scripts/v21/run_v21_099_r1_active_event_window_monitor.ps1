param(
    [string]$Root = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string]$RunDate = (Get-Date -Format "yyyy-MM-dd")
)

$venvActivate = Join-Path $Root ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) { . $venvActivate }

$script = Join-Path $Root "scripts\v21\v21_099_r1_active_event_window_monitor.py"
$test = Join-Path $Root "scripts\v21\test_v21_099_r1_active_event_window_monitor.py"

python $script --root $Root --run-date $RunDate
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python $test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
