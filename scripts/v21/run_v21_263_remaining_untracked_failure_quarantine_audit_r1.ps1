param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
Set-Location $RepoRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "scripts\v21\v21_263_remaining_untracked_failure_quarantine_audit_r1.py"
& $Python $Script --repo-root $RepoRoot --dry-run
exit $LASTEXITCODE
