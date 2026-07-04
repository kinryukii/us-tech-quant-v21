param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$CacheRoot = "D:\us-tech-quant-cache",
    [string]$OutputDir = "",
    [switch]$DryRun,
    [switch]$Execute,
    [double]$LargeFileThresholdMB = 5,
    [switch]$IncludeV20,
    [switch]$IncludeShared,
    [switch]$AllowUserArchiveMove,
    [switch]$FailOnViolation,
    [double]$MaxAllowedRepoOutputsMB = -1
)
$ErrorActionPreference = "Stop"
Set-Location $RepoRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "scripts\v21\v21_260_retention_enforced_output_guard_r1.py"
$Mode = "DryRun"
if ($Execute) { $Mode = "Execute" }
$ArgsList = @(
    $Script,
    "--repo-root", $RepoRoot,
    "--cache-root", $CacheRoot,
    "--mode", $Mode,
    "--large-file-threshold-mb", "$LargeFileThresholdMB"
)
if ($OutputDir) { $ArgsList += @("--output-dir", $OutputDir) }
if ($IncludeV20) { $ArgsList += "--include-v20" }
if ($IncludeShared) { $ArgsList += "--include-shared" }
if ($AllowUserArchiveMove) { $ArgsList += "--allow-user-archive-move" }
if ($FailOnViolation) { $ArgsList += "--fail-on-violation" }
if ($MaxAllowedRepoOutputsMB -ge 0) { $ArgsList += @("--max-allowed-repo-outputs-mb", "$MaxAllowedRepoOutputsMB") }
& $Python @ArgsList
exit $LASTEXITCODE
