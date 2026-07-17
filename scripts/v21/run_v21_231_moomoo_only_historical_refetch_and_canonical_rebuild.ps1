$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
. (Join-Path $RepoRoot "scripts\common\storage_paths.ps1"); $Storage=Get-UstqStoragePaths -RepoRoot $RepoRoot
$Python = $Storage.python_exe
$OutputDir = Join-Path $Storage.daily_root "current\V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD"
$V230OutputDir = Join-Path $Storage.daily_root "prerequisites\v21\V21.230_MOOMOO_ONLY_HISTORICAL_REFETCH_DRY_RUN"
$V230R1OutputDir = Join-Path $Storage.daily_root "prerequisites\v21\V21.230_R1_MOOMOO_OPEND_READINESS_AND_PERMISSION_PROBE"
$SummaryPath = Join-Path $OutputDir "v21_231_summary.json"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "MISSING_EXTERNAL_PYTHON:$Python" }
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Set-Location $RepoRoot

& $Python "scripts\v21\v21_231_moomoo_only_historical_refetch_and_canonical_rebuild.py" `
  --repo-root $RepoRoot `
  --output-dir $OutputDir `
  --v21-230-output-dir $V230OutputDir `
  --v21-230-r1-output-dir $V230R1OutputDir

$ExitCode = $LASTEXITCODE
Write-Host "V21.231 summary: $SummaryPath"
exit $ExitCode
