param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path $RepoRoot
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

$ArgsList = @("scripts/v21/v21_202_repo_safe_cleanup_audit_and_cache_purge.py", "--repo-root", $Root)
if ($Execute) { $ArgsList += "--execute" }
& $Python @ArgsList
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$SummaryPath = Join-Path $Root "outputs/v21/V21.202_REPO_SAFE_CLEANUP_AUDIT_AND_CACHE_PURGE/v21_202_summary.json"
$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
Write-Output "final_status=$($Summary.final_status)"
Write-Output "final_decision=$($Summary.final_decision)"
Write-Output "delete_allowed_total=$($Summary.delete_allowed_total)"
Write-Output "deleted_total=$($Summary.deleted_total)"
Write-Output "access_denied_total=$($Summary.access_denied_total)"
Write-Output "broker_action_allowed=$($Summary.broker_action_allowed)"
if ($Summary.final_status -notlike "PASS*" -and $Summary.final_status -notlike "WARN*") { exit 1 }
exit 0
