$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
. (Join-Path $RepoRoot "scripts\common\storage_paths.ps1"); $Storage=Get-UstqStoragePaths -RepoRoot $RepoRoot
$Python = $Storage.python_exe
$OutputDir = Join-Path $Storage.daily_root "current\V21.233_MOOMOO_ONLY_ABCDE_RERUN"
$V231OutputDir = Join-Path $Storage.daily_root "current\V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD"
if(-not(Test-Path $V231OutputDir)){$V231OutputDir=Join-Path $Storage.daily_root "migrated_from_repo\outputs\v21\V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD"}
$V232OutputDir = Join-Path $Storage.daily_root "current\V21.232_MOOMOO_ONLY_DRAM_DAILY_AND_INTRADAY_PLAN"
$SummaryPath = Join-Path $OutputDir "v21_233_summary.json"

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Set-Location $RepoRoot

& $Python "scripts\v21\v21_233_moomoo_only_abcde_rerun.py" `
  --repo-root $RepoRoot `
  --output-dir $OutputDir `
  --v21-231-output-dir $V231OutputDir `
  --v21-232-output-dir $V232OutputDir

$ExitCode = $LASTEXITCODE
Write-Host "V21.233 summary: $SummaryPath"
exit $ExitCode
