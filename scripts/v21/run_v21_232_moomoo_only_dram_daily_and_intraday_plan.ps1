$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$StorageModule = Join-Path $RepoRoot "scripts\common\storage_paths.ps1"
if (-not (Test-Path -LiteralPath $StorageModule)) { throw "Storage path module not found: $StorageModule" }
. $StorageModule
$PythonExe = Get-UstqPythonExecutable
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw "External Python executable not found: $PythonExe" }
$ResolvedPython = (Resolve-Path -LiteralPath $PythonExe).Path
$RepoPrefix = ([IO.Path]::GetFullPath([string]$RepoRoot)).TrimEnd('\') + '\'
if ($ResolvedPython.StartsWith($RepoPrefix, [System.StringComparison]::OrdinalIgnoreCase)) { throw "Python executable must be outside repo: $ResolvedPython" }
$OutputDir = Join-Path (Get-UstqDailyRoot) "current\V21.232_MOOMOO_ONLY_DRAM_DAILY_AND_INTRADAY_PLAN"
$V231OutputDir = Join-Path (Get-UstqDailyRoot) "current\V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD"
if (-not (Test-Path -LiteralPath $V231OutputDir)) { $V231OutputDir = Join-Path (Get-UstqDailyRoot) "migrated_from_repo\outputs\v21\V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD" }
Assert-UstqExternalPath $OutputDir
$SummaryPath = Join-Path $OutputDir "v21_232_summary.json"

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Set-Location $RepoRoot

$env:USTQ_REPO_ROOT=$RepoRoot; $env:USTQ_DATA_ROOT=(Get-UstqDataRoot); $env:USTQ_CACHE_ROOT=(Get-UstqCacheRoot); $env:USTQ_DAILY_ROOT=(Get-UstqDailyRoot); $env:USTQ_RESULTS_ROOT=(Get-UstqResultsRoot); $env:USTQ_ENVS_ROOT=(Get-UstqEnvsRoot); $env:USTQ_PYTHON_EXE=$ResolvedPython
& $ResolvedPython "scripts\v21\v21_232_moomoo_only_dram_daily_and_intraday_plan.py" `
  --repo-root $RepoRoot `
  --output-dir $OutputDir `
  --v21-231-output-dir $V231OutputDir

$ExitCode = $LASTEXITCODE
Write-Host "V21.232 summary: $SummaryPath"
exit $ExitCode
