param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$ArchiveRoot = "",
    [string]$FreezeId = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path $RepoRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) { $Python = $VenvPython } else { $Python = "python" }

$OutputDir = Join-Path $Root "outputs\v21\V21.224_PRE_MIGRATION_RESULT_ARCHIVE_AND_MANIFEST_FREEZE"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$ArgsList = @(
    (Join-Path $Root "scripts\v21\v21_224_pre_migration_result_archive_and_manifest_freeze.py"),
    "--repo-root",
    $Root,
    "--output-dir",
    $OutputDir
)

if ($ArchiveRoot -ne "") {
    $ArgsList += @("--archive-root", $ArchiveRoot)
}
if ($FreezeId -ne "") {
    $ArgsList += @("--freeze-id", $FreezeId)
}
if ($DryRun) {
    $ArgsList += "--dry-run"
}

& $Python @ArgsList
$ExitCode = $LASTEXITCODE
$SummaryPath = Join-Path $OutputDir "v21_224_summary.json"
Write-Host "final_summary_path=$SummaryPath"
exit $ExitCode
