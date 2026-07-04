$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$OutputDir = Join-Path $RepoRoot "outputs\v21\V21.234_MINIMAL_MOOMOO_ONLY_DAILY_RESEARCH_CHAIN"
$V231OutputDir = Join-Path $RepoRoot "outputs\v21\V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD"
$V232OutputDir = Join-Path $RepoRoot "outputs\v21\V21.232_MOOMOO_ONLY_DRAM_DAILY_AND_INTRADAY_PLAN"
$V233OutputDir = Join-Path $RepoRoot "outputs\v21\V21.233_MOOMOO_ONLY_ABCDE_RERUN"
$SummaryPath = Join-Path $OutputDir "v21_234_summary.json"

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Set-Location $RepoRoot

& $Python "scripts\v21\v21_234_minimal_moomoo_only_daily_research_chain.py" `
  --repo-root $RepoRoot `
  --output-dir $OutputDir `
  --v21-231-output-dir $V231OutputDir `
  --v21-232-output-dir $V232OutputDir `
  --v21-233-output-dir $V233OutputDir

$ExitCode = $LASTEXITCODE
Write-Host "V21.234 summary: $SummaryPath"
exit $ExitCode
