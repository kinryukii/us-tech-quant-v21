$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$OutputDir = Join-Path $RepoRoot "outputs\v21\V21.232_MOOMOO_ONLY_DRAM_DAILY_AND_INTRADAY_PLAN"
$V231OutputDir = Join-Path $RepoRoot "outputs\v21\V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD"
$SummaryPath = Join-Path $OutputDir "v21_232_summary.json"

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Set-Location $RepoRoot

& $Python "scripts\v21\v21_232_moomoo_only_dram_daily_and_intraday_plan.py" `
  --repo-root $RepoRoot `
  --output-dir $OutputDir `
  --v21-231-output-dir $V231OutputDir

$ExitCode = $LASTEXITCODE
Write-Host "V21.232 summary: $SummaryPath"
exit $ExitCode
