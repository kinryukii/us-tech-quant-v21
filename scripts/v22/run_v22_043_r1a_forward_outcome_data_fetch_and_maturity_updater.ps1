param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant",
    [bool]$UseMoomooReadOnlyBars = $true,
    [string]$BarInterval = "1m",
    [bool]$AllowIncompleteBars = $false,
    [string]$EventId = "",
    [Alias("Host")]
    [string]$MoomooHost = "127.0.0.1",
    [int]$Port = 18441
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_043_r1a_forward_outcome_data_fetch_and_maturity_updater.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$SummaryPath = Join-Path $RepoRoot "outputs\v22\V22.043_R1A_FORWARD_OUTCOME_DATA_FETCH_AND_MATURITY_UPDATER\v22_043_r1a_summary.json"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$ArgsList = @($Script, "--repo-root", $RepoRoot, "--bar-interval", $BarInterval, "--host", $MoomooHost, "--port", $Port)
if ($Execute) { $ArgsList += "--execute" }
if (-not $UseMoomooReadOnlyBars) { $ArgsList += "--no-use-moomoo-readonly-bars" }
if ($AllowIncompleteBars) { $ArgsList += "--allow-incomplete-bars" }
if ($EventId -ne "") { $ArgsList += @("--event-id", $EventId) }

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
            "final_status", "final_decision", "event_id_latest", "timezone_alignment_ok",
            "forward_data_available", "horizon_mature_count", "forward_bar_available_count",
            "newly_completed_outcome_count", "remaining_pending_outcome_count",
            "total_completed_outcome_count", "scorecard_available", "primary_unavailable_reason",
            "broker_action_allowed", "official_adoption_allowed"
        )) {
            Write-Output "$Key=$($Summary.$Key)"
        }
    } catch {
        Write-Output "final_status=UNREADABLE_SUMMARY"
        Write-Output "final_decision=UNREADABLE_SUMMARY"
    }
}

exit $PythonExit
