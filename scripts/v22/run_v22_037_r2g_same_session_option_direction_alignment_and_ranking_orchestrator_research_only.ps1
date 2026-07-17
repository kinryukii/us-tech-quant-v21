param(
    [switch]$Execute,
    [switch]$AuditOnly,
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$ManifestPath = "",
    [double]$MaxDirectionPanelGapMinutes = 30,
    [double]$MaxPanelAgeMinutes = 90,
    [double]$MaxDirectionAgeMinutes = 90,
    [int]$ChildTimeoutSeconds = 1800
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

$Script = Join-Path $RepoRoot "scripts\v22\v22_037_r2g_same_session_option_direction_alignment_and_ranking_orchestrator_research_only.py"
$ArgsList = @(
    $Script,
    "--repo-root", $RepoRoot,
    "--max-direction-panel-gap-minutes", "$MaxDirectionPanelGapMinutes",
    "--max-panel-age-minutes", "$MaxPanelAgeMinutes",
    "--max-direction-age-minutes", "$MaxDirectionAgeMinutes",
    "--child-timeout-seconds", "$ChildTimeoutSeconds"
)

if ($ManifestPath -ne "") {
    $ArgsList += @("--manifest-path", $ManifestPath)
}
if ($Execute -and -not $AuditOnly) {
    $ArgsList += "--execute"
}
else {
    $ArgsList += "--audit-only"
}

Set-Location $RepoRoot
& $Python @ArgsList
$ExitCode = $LASTEXITCODE

Write-Output "broker_action_allowed=False"
Write-Output "official_adoption_allowed=False"
Write-Output "research_only=True"
exit $ExitCode
