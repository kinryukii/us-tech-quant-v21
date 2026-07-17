$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
. (Join-Path $RepoRoot "scripts\common\storage_paths.ps1")
$Storage = Get-UstqStoragePaths -RepoRoot $RepoRoot
$Python = $Storage.python_exe
$OutputDir = Join-Path $Storage.daily_root "prerequisites\v21\V21.230_MOOMOO_ONLY_HISTORICAL_REFETCH_DRY_RUN"
$SummaryPath = Join-Path $OutputDir "v21_230_summary.json"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "MISSING_EXTERNAL_PYTHON:$Python" }
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Set-Location $RepoRoot

& $Python "scripts\v21\v21_230_moomoo_only_historical_refetch_dry_run.py" `
  --repo-root $RepoRoot `
  --output-dir $OutputDir

$ExitCode = $LASTEXITCODE
Write-Host "V21.230 summary: $SummaryPath"
exit $ExitCode
