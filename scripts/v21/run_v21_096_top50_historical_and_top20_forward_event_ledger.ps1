param(
    [string]$Root = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [switch]$EnableNetwork
)

$venvActivate = Join-Path $Root ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) { . $venvActivate }

$script = Join-Path $Root "scripts\v21\v21_096_top50_historical_and_top20_forward_event_ledger.py"
$test = Join-Path $Root "scripts\v21\test_v21_096_top50_historical_and_top20_forward_event_ledger.py"
$arguments = @($script, "--root", $Root)
if ($EnableNetwork) { $arguments += "--enable-network" }

python @arguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python $test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
