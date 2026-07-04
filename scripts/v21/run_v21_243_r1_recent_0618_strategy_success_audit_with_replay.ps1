param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$OutputDir = "",
    [string]$PricePath = "",
    [string]$ReplayPath = ""
)

$ErrorActionPreference = "Stop"
Set-Location $RepoRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "scripts\v21\v21_243_r1_recent_0618_strategy_success_audit_with_replay.py"
$ArgsList = @($Script, "--repo-root", $RepoRoot)
if ($OutputDir) { $ArgsList += @("--output-dir", $OutputDir) }
if ($PricePath) { $ArgsList += @("--price-path", $PricePath) }
if ($ReplayPath) { $ArgsList += @("--replay-path", $ReplayPath) }
& $Python @ArgsList
$ExitCode = $LASTEXITCODE
$SummaryPath = if ($OutputDir) { Join-Path $OutputDir "v21_243_r1_summary.json" } else { Join-Path $RepoRoot "outputs\v21\V21.243_R1_RECENT_0618_STRATEGY_SUCCESS_AUDIT_WITH_REPLAY\v21_243_r1_summary.json" }
Write-Host "V21.243_R1 summary: $SummaryPath"
exit $ExitCode
