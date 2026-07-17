param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant",
    [bool]$UseLatestV22042R2 = $true,
    [bool]$AppendLedger = $true,
    [bool]$EvaluateForwardOutcomes = $true,
    [bool]$AllowDuplicateSameMinute = $false,
    [Alias("Host")]
    [string]$MoomooHost = "127.0.0.1",
    [int]$Port = 18441
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_043_direction_gate_forward_outcome_tracker_r1.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$SummaryPath = Join-Path $RepoRoot "outputs\v22\V22.043_DIRECTION_GATE_FORWARD_OUTCOME_TRACKER_R1\v22_043_summary.json"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$ArgsList = @($Script, "--repo-root", $RepoRoot, "--host", $MoomooHost, "--port", $Port)
if ($Execute) { $ArgsList += "--execute" }
if (-not $UseLatestV22042R2) { $ArgsList += "--no-use-latest-v22-042-r2" }
if (-not $AppendLedger) { $ArgsList += "--no-append-ledger" }
if (-not $EvaluateForwardOutcomes) { $ArgsList += "--no-evaluate-forward-outcomes" }
if ($AllowDuplicateSameMinute) { $ArgsList += "--allow-duplicate-same-minute" }

Set-Location $RepoRoot
& $Python @ArgsList
$PythonExit = $LASTEXITCODE

Write-Output "final_summary_path=$SummaryPath"
$SummaryExists = Test-Path $SummaryPath
Write-Output "summary_exists=$SummaryExists"
if ($SummaryExists) {
    try {
        $Summary = Get-Content -Raw -Path $SummaryPath | ConvertFrom-Json
        foreach ($Key in @(
            "final_status", "final_decision", "event_archived", "event_id",
            "strict_official_final_direction_label", "strict_official_wait_state",
            "semiconductor_only_shadow_direction_label", "semiconductor_only_shadow_candidate_count",
            "relaxed_broad_shadow_direction_label", "relaxed_broad_shadow_candidate_count",
            "pending_outcome_count", "completed_outcome_count",
            "shadow_vs_strict_scorecard_available", "broker_action_allowed", "official_adoption_allowed"
        )) {
            Write-Output "$Key=$($Summary.$Key)"
        }
    } catch {
        Write-Output "final_status=UNREADABLE_SUMMARY"
        Write-Output "final_decision=UNREADABLE_SUMMARY"
    }
}

exit $PythonExit
