param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$V21226OutputDir = "",
    [string]$CacheRoot = "D:\us-tech-quant-cache",
    [string]$ArchiveRoot = "D:\us-tech-quant-archive",
    [string]$QuarantineRoot = "D:\us-tech-quant-quarantine",
    [switch]$HashLarge
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path $RepoRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) { $Python = $VenvPython } else { $Python = "python" }

$OutputDir = Join-Path $Root "outputs\v21\V21.227_EXTERNAL_CACHE_AND_ARCHIVE_MIGRATION_DRY_RUN"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$ArgsList = @(
    (Join-Path $Root "scripts\v21\v21_227_external_cache_and_archive_migration_dry_run.py"),
    "--repo-root", $Root,
    "--output-dir", $OutputDir,
    "--cache-root", $CacheRoot,
    "--archive-root", $ArchiveRoot,
    "--quarantine-root", $QuarantineRoot
)
if ($V21226OutputDir -ne "") { $ArgsList += @("--v21-226-output-dir", $V21226OutputDir) }
if ($HashLarge) { $ArgsList += "--hash-large" }

& $Python @ArgsList
$ExitCode = $LASTEXITCODE
$SummaryPath = Join-Path $OutputDir "v21_227_summary.json"
Write-Host "final_summary_path=$SummaryPath"
exit $ExitCode
