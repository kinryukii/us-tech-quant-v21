param(
    [string]$Root = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string]$Tickers = "MU,WDC,STX,NVDA",
    [int]$LookaheadDays = 120,
    [switch]$AllowLowConfidenceEarnings,
    [switch]$ReuseR6Importer
)

$venvActivate = Join-Path $Root ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) { . $venvActivate }

$script = Join-Path $Root "scripts\v21\v21_095_r7_auto_event_source_autofiller.py"
$test = Join-Path $Root "scripts\v21\test_v21_095_r7_auto_event_source_autofiller.py"
$arguments = @(
    $script, "--root", $Root, "--earnings-provider", "api",
    "--tickers", $Tickers, "--lookahead-days", $LookaheadDays
)
if ($AllowLowConfidenceEarnings) { $arguments += "--allow-low-confidence-earnings" }
if ($ReuseR6Importer) { $arguments += "--reuse-r6-importer" }

python @arguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python $test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
