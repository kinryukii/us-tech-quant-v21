param(
    [string]$RepoRoot = "D:\us-tech-quant"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path $RepoRoot
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

& $Python scripts/v21/v21_207_compress_only_zip_copy_creation.py --repo-root $Root
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$SummaryPath = Join-Path $Root "outputs/v21/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION/v21_207_summary.json"
$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
Write-Output "final_status=$($Summary.final_status)"
Write-Output "final_decision=$($Summary.final_decision)"
Write-Output "approved_candidate_count=$($Summary.approved_candidate_count)"
Write-Output "zip_created_count=$($Summary.zip_created_count)"
Write-Output "zip_skipped_existing_valid_count=$($Summary.zip_skipped_existing_valid_count)"
Write-Output "zip_failed_count=$($Summary.zip_failed_count)"
Write-Output "all_sources_unchanged_after=$($Summary.all_sources_unchanged_after)"
Write-Output "deletion_performed=$($Summary.deletion_performed)"
Write-Output "broker_action_allowed=$($Summary.broker_action_allowed)"
if ($Summary.final_status -notlike "PASS*" -and $Summary.final_status -notlike "WARN*") { exit 1 }
exit 0
