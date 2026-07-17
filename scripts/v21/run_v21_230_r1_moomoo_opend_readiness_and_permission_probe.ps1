$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
. (Join-Path $RepoRoot "scripts\common\storage_paths.ps1")
$Storage = Get-UstqStoragePaths -RepoRoot $RepoRoot
$Python = $Storage.python_exe
$OutputDir = Join-Path $Storage.daily_root "prerequisites\v21\V21.230_R1_MOOMOO_OPEND_READINESS_AND_PERMISSION_PROBE"
$V230OutputDir = Join-Path $Storage.daily_root "prerequisites\v21\V21.230_MOOMOO_ONLY_HISTORICAL_REFETCH_DRY_RUN"
$SummaryPath = Join-Path $OutputDir "v21_230_r1_summary.json"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "MISSING_EXTERNAL_PYTHON:$Python" }
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Set-Location $RepoRoot

& $Python "scripts\v21\v21_230_r1_moomoo_opend_readiness_and_permission_probe.py" `
  --repo-root $RepoRoot `
  --output-dir $OutputDir `
  --v21-230-output-dir $V230OutputDir

$ExitCode = $LASTEXITCODE
Write-Host "V21.230_R1 summary: $SummaryPath"
exit $ExitCode
