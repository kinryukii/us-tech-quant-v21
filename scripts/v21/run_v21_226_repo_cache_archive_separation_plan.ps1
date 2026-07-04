param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$V21225OutputDir = "",
    [string]$V21224OutputDir = "",
    [string]$CacheRoot = "D:\us-tech-quant-cache",
    [string]$ArchiveRoot = "D:\us-tech-quant-archive",
    [string]$QuarantineRoot = "D:\us-tech-quant-quarantine"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path $RepoRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) { $Python = $VenvPython } else { $Python = "python" }

$OutputDir = Join-Path $Root "outputs\v21\V21.226_REPO_CACHE_ARCHIVE_SEPARATION_PLAN"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$ArgsList = @(
    (Join-Path $Root "scripts\v21\v21_226_repo_cache_archive_separation_plan.py"),
    "--repo-root", $Root,
    "--output-dir", $OutputDir,
    "--cache-root", $CacheRoot,
    "--archive-root", $ArchiveRoot,
    "--quarantine-root", $QuarantineRoot
)
if ($V21225OutputDir -ne "") { $ArgsList += @("--v21-225-output-dir", $V21225OutputDir) }
if ($V21224OutputDir -ne "") { $ArgsList += @("--v21-224-output-dir", $V21224OutputDir) }

& $Python @ArgsList
$ExitCode = $LASTEXITCODE
$SummaryPath = Join-Path $OutputDir "v21_226_summary.json"
Write-Host "final_summary_path=$SummaryPath"
exit $ExitCode
