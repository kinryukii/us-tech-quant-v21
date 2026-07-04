param(
    [string]$InputDir,
    [string]$InputDashboard,
    [string]$InputSummary,
    [string]$OutputDir
)

$ErrorActionPreference = "Stop"

$argsList = @("scripts/v21/v21_185_dram_intraday_trigger_event_archive_and_daily_append.py")
if ($InputDir) {
    $argsList += @("--input-dir", $InputDir)
}
if ($InputDashboard) {
    $argsList += @("--input-dashboard", $InputDashboard)
}
if ($InputSummary) {
    $argsList += @("--input-summary", $InputSummary)
}
if ($OutputDir) {
    $argsList += @("--output-dir", $OutputDir)
}

python @argsList
$code = $LASTEXITCODE

$resolvedOutputDir = if ($OutputDir) {
    $OutputDir
} else {
    "outputs/v21/V21.185_DRAM_INTRADAY_TRIGGER_EVENT_ARCHIVE_AND_DAILY_APPEND"
}
$summaryPath = Join-Path $resolvedOutputDir "v21_185_summary.json"

Write-Host ("OUTPUT_DIR=" + $resolvedOutputDir)
Write-Host ("SUMMARY_PATH=" + $summaryPath)

exit $code
