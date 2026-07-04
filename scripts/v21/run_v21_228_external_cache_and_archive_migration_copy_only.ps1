param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$V21227OutputDir = "",
    [string]$CacheRoot = "D:\us-tech-quant-cache",
    [string]$ArchiveRoot = "D:\us-tech-quant-archive",
    [string]$QuarantineRoot = "D:\us-tech-quant-quarantine",
    [switch]$ForceRecopySameHash
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path $RepoRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) { $Python = $VenvPython } else { $Python = "python" }

$OutputDir = Join-Path $Root "outputs\v21\V21.228_EXTERNAL_CACHE_AND_ARCHIVE_MIGRATION_COPY_ONLY"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$ArgsList = @(
    (Join-Path $Root "scripts\v21\v21_228_external_cache_and_archive_migration_copy_only.py"),
    "--repo-root", $Root,
    "--output-dir", $OutputDir,
    "--cache-root", $CacheRoot,
    "--archive-root", $ArchiveRoot,
    "--quarantine-root", $QuarantineRoot
)
if ($V21227OutputDir -ne "") { $ArgsList += @("--v21-227-output-dir", $V21227OutputDir) }
if ($ForceRecopySameHash) { $ArgsList += "--force-recopy-same-hash" }

& $Python @ArgsList
$ExitCode = $LASTEXITCODE
$SummaryPath = Join-Path $OutputDir "v21_228_summary.json"
Write-Host "final_summary_path=$SummaryPath"
exit $ExitCode
