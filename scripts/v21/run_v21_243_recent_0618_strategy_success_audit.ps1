param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$OutputDir = "",
    [string]$PricePath = ""
)

$ErrorActionPreference = "Stop"
Set-Location $RepoRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "scripts\v21\v21_243_recent_0618_strategy_success_audit.py"
$ArgsList = @($Script, "--repo-root", $RepoRoot)
if ($OutputDir) { $ArgsList += @("--output-dir", $OutputDir) }
if ($PricePath) { $ArgsList += @("--price-path", $PricePath) }
& $Python @ArgsList
$ExitCode = $LASTEXITCODE
$SummaryPath = if ($OutputDir) { Join-Path $OutputDir "v21_243_summary.json" } else { Join-Path $RepoRoot "outputs\v21\V21.243_RECENT_0618_STRATEGY_SUCCESS_AUDIT\v21_243_summary.json" }
Write-Host "V21.243 summary: $SummaryPath"
exit $ExitCode
