param(
    [string]$Root = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [ValidateSet("earningscalendar", "upcomingearnings")]
    [string]$ApiNinjasEndpoint = "earningscalendar",
    [string]$Tickers = "MU,WDC,STX,NVDA",
    [int]$LookaheadDays = 120,
    [switch]$AllowLowConfidenceEarnings,
    [switch]$ReuseR6Importer,
    [switch]$AllowPastForwardSnapshot,
    [switch]$UseDateRange
)

$venvActivate = Join-Path $Root ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) { . $venvActivate }

$script = Join-Path $Root "scripts\v21\v21_095_r7a_api_ninjas_earnings_provider_contract_repair.py"
$test = Join-Path $Root "scripts\v21\test_v21_095_r7a_api_ninjas_earnings_provider_contract_repair.py"
$arguments = @(
    $script, "--root", $Root,
    "--api-ninjas-endpoint", $ApiNinjasEndpoint,
    "--tickers", $Tickers,
    "--lookahead-days", $LookaheadDays
)
if ($AllowLowConfidenceEarnings) { $arguments += "--allow-low-confidence-earnings" }
if ($ReuseR6Importer) { $arguments += "--reuse-r6-importer" }
if ($AllowPastForwardSnapshot) { $arguments += "--allow-past-forward-snapshot" }
if ($UseDateRange) { $arguments += "--api-ninjas-use-date-range" }

python @arguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python $test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
