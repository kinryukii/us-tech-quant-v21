param(
    [switch]$OperatorApproveYahooDownload,
    [string]$StartDate = "2020-01-01",
    [string]$EndDate = "2026-06-16"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_214_operator_approved_historical_price_and_membership_input_fill_or_yahoo_cache_build.py"

if ($OperatorApproveYahooDownload) {
    python $Runner --operator-approve-yahoo-download --start-date $StartDate --end-date $EndDate
} else {
    python $Runner --start-date $StartDate --end-date $EndDate
}
