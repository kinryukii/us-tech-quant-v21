param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [switch]$DryRun,
    [double]$LargeFileThresholdMB = 5,
    [switch]$IncludeUntrackedContentHash,
    [int]$MaxRows = 100000
)
$ErrorActionPreference = "Stop"
Set-Location $RepoRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "scripts\v21\v21_262_git_worktree_dirty_state_triage_r1.py"
$ArgsList = @(
    $Script,
    "--repo-root", $RepoRoot,
    "--large-file-threshold-mb", "$LargeFileThresholdMB",
    "--max-rows", "$MaxRows"
)
if ($IncludeUntrackedContentHash) { $ArgsList += "--include-untracked-content-hash" }
& $Python @ArgsList
exit $LASTEXITCODE
