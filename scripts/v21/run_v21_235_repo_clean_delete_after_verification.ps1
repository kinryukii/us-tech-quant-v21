$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$OutputDir = Join-Path $RepoRoot "outputs\v21\V21.235_REPO_CLEAN_DELETE_AFTER_VERIFICATION"
$SummaryPath = Join-Path $OutputDir "v21_235_summary.json"

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Set-Location $RepoRoot

& $Python "scripts\v21\v21_235_repo_clean_delete_after_verification.py" `
  --repo-root $RepoRoot `
  --output-dir $OutputDir `
  --allow-delete

$ExitCode = $LASTEXITCODE
Write-Host "V21.235 summary: $SummaryPath"
exit $ExitCode
