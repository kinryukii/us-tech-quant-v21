param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$OutputDir = "",
    [string]$PricePath = ""
)

$ErrorActionPreference = "Stop"
Set-Location $RepoRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "scripts\v21\v21_244_abcde_retrospective_replay_0618_to_0629.py"
$ArgsList = @($Script, "--repo-root", $RepoRoot)
if ($OutputDir) { $ArgsList += @("--output-dir", $OutputDir) }
if ($PricePath) { $ArgsList += @("--price-path", $PricePath) }
& $Python @ArgsList
$ExitCode = $LASTEXITCODE
$SummaryPath = if ($OutputDir) { Join-Path $OutputDir "v21_244_summary.json" } else { Join-Path $RepoRoot "outputs\v21\V21.244_ABCDE_RETROSPECTIVE_REPLAY_0618_TO_0629\v21_244_summary.json" }
Write-Host "V21.244 summary: $SummaryPath"
exit $ExitCode
