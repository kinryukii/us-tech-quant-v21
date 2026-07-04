param(
    [string]$RepoRoot = "D:\us-tech-quant"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path $RepoRoot
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

& $Python scripts/v21/v21_203_repo_size_attribution_and_safe_purge_candidate_audit.py --repo-root $Root
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$SummaryPath = Join-Path $Root "outputs/v21/V21.203_REPO_SIZE_ATTRIBUTION_AND_SAFE_PURGE_CANDIDATE_AUDIT/v21_203_summary.json"
$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
Write-Output "final_status=$($Summary.final_status)"
Write-Output "final_decision=$($Summary.final_decision)"
Write-Output "safe_purge_candidate_count=$($Summary.safe_purge_candidate_count)"
Write-Output "protected_missing_count=$($Summary.protected_missing_count)"
Write-Output "deletion_performed=$($Summary.deletion_performed)"
Write-Output "broker_action_allowed=$($Summary.broker_action_allowed)"
if ($Summary.final_status -notlike "PASS*" -and $Summary.final_status -notlike "WARN*") { exit 1 }
exit 0
