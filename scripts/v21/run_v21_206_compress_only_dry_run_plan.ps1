param(
    [string]$RepoRoot = "D:\us-tech-quant"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path $RepoRoot
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

& $Python scripts/v21/v21_206_compress_only_dry_run_plan.py --repo-root $Root
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$SummaryPath = Join-Path $Root "outputs/v21/V21.206_COMPRESS_ONLY_DRY_RUN_PLAN/v21_206_summary.json"
$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
Write-Output "final_status=$($Summary.final_status)"
Write-Output "final_decision=$($Summary.final_decision)"
Write-Output "candidate_count_from_v21_205=$($Summary.candidate_count_from_v21_205)"
Write-Output "candidate_count_after_exclusions=$($Summary.candidate_count_after_exclusions)"
Write-Output "planned_compression_count=$($Summary.planned_compression_count)"
Write-Output "compression_performed=$($Summary.compression_performed)"
Write-Output "deletion_performed=$($Summary.deletion_performed)"
Write-Output "broker_action_allowed=$($Summary.broker_action_allowed)"
if ($Summary.final_status -notlike "PASS*" -and $Summary.final_status -notlike "WARN*") { exit 1 }
exit 0
