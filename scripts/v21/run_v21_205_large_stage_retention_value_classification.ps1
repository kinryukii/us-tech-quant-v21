param(
    [string]$RepoRoot = "D:\us-tech-quant"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path $RepoRoot
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

& $Python scripts/v21/v21_205_large_stage_retention_value_classification.py --repo-root $Root
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$SummaryPath = Join-Path $Root "outputs/v21/V21.205_LARGE_STAGE_RETENTION_VALUE_CLASSIFICATION/v21_205_summary.json"
$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
Write-Output "final_status=$($Summary.final_status)"
Write-Output "final_decision=$($Summary.final_decision)"
Write-Output "large_stage_count=$($Summary.large_stage_count)"
Write-Output "compress_only_candidate_count=$($Summary.compress_only_candidate_count)"
Write-Output "manual_review_low_value_candidate_count=$($Summary.manual_review_low_value_candidate_count)"
Write-Output "deletion_performed=$($Summary.deletion_performed)"
Write-Output "broker_action_allowed=$($Summary.broker_action_allowed)"
if ($Summary.final_status -notlike "PASS*" -and $Summary.final_status -notlike "WARN*") { exit 1 }
exit 0
