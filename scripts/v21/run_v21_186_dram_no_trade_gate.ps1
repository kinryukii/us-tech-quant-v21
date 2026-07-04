param(
    [string]$V185Dir,
    [string]$V184Dir,
    [string]$PlanDir,
    [string]$OutputDir
)

$ErrorActionPreference = "Stop"

$argsList = @("scripts/v21/v21_186_dram_no_trade_gate.py")
if ($V185Dir) {
    $argsList += @("--v185-dir", $V185Dir)
}
if ($V184Dir) {
    $argsList += @("--v184-dir", $V184Dir)
}
if ($PlanDir) {
    $argsList += @("--plan-dir", $PlanDir)
}
if ($OutputDir) {
    $argsList += @("--output-dir", $OutputDir)
}

python @argsList
$code = $LASTEXITCODE

$resolvedOutputDir = if ($OutputDir) {
    $OutputDir
} else {
    "outputs/v21/V21.186_DRAM_NO_TRADE_GATE"
}
$summaryPath = Join-Path $resolvedOutputDir "v21_186_summary.json"

Write-Host ("OUTPUT_DIR=" + $resolvedOutputDir)
Write-Host ("SUMMARY_PATH=" + $summaryPath)

exit $code
