param(
    [string]$RepoRoot = "D:\us-tech-quant"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path $RepoRoot
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

& $Python scripts/v21/v21_204_outputs_v21_archive_candidate_audit.py --repo-root $Root
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$SummaryPath = Join-Path $Root "outputs/v21/V21.204_OUTPUTS_V21_ARCHIVE_CANDIDATE_AUDIT/v21_204_summary.json"
$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
Write-Output "final_status=$($Summary.final_status)"
Write-Output "final_decision=$($Summary.final_decision)"
Write-Output "total_stage_dirs_scanned=$($Summary.total_stage_dirs_scanned)"
Write-Output "tier_1_archive_candidate_count=$($Summary.tier_1_archive_candidate_count)"
Write-Output "tier_2_review_candidate_count=$($Summary.tier_2_review_candidate_count)"
Write-Output "deletion_performed=$($Summary.deletion_performed)"
Write-Output "broker_action_allowed=$($Summary.broker_action_allowed)"
if ($Summary.final_status -notlike "PASS*" -and $Summary.final_status -notlike "WARN*") { exit 1 }
exit 0
