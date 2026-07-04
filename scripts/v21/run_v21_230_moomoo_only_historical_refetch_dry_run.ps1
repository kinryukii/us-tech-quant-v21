$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$OutputDir = Join-Path $RepoRoot "outputs\v21\V21.230_MOOMOO_ONLY_HISTORICAL_REFETCH_DRY_RUN"
$SummaryPath = Join-Path $OutputDir "v21_230_summary.json"

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Set-Location $RepoRoot

& $Python "scripts\v21\v21_230_moomoo_only_historical_refetch_dry_run.py" `
  --repo-root $RepoRoot `
  --output-dir $OutputDir

$ExitCode = $LASTEXITCODE
Write-Host "V21.230 summary: $SummaryPath"
exit $ExitCode
