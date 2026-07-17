param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$InputPath = "",
    [string]$UnderlyingSnapshotPath = "",
    [string]$OutputRoot = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_037_r1a_option_underlying_price_injection_repair_research_only.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

$ArgsList = @(
    $Script,
    "--repo-root", $RepoRoot
)
if ($InputPath -ne "") {
    $ArgsList += @("--input-path", $InputPath)
}
if ($UnderlyingSnapshotPath -ne "") {
    $ArgsList += @("--underlying-snapshot-path", $UnderlyingSnapshotPath)
}
if ($OutputRoot -ne "") {
    $ArgsList += @("--output-root", $OutputRoot)
}
if ($Execute) {
    $ArgsList += "--execute"
} else {
    Write-Output "PLAN_ONLY=True"
    Write-Output "execute_required_to_write_outputs=True"
}

Set-Location $RepoRoot
& $Python @ArgsList
$PythonExit = $LASTEXITCODE

$SummaryPath = if ($OutputRoot -ne "") { Join-Path $OutputRoot "v22_037_r1a_summary.json" } else { Join-Path $RepoRoot "outputs\v22\V22.037_R1A_OPTION_UNDERLYING_PRICE_INJECTION_REPAIR_RESEARCH_ONLY\v22_037_r1a_summary.json" }
Write-Output "final_summary_path=$SummaryPath"
$SummaryExists = Test-Path $SummaryPath
Write-Output "summary_exists=$SummaryExists"
if ($SummaryExists) {
    try {
        $Summary = Get-Content -Raw -Path $SummaryPath | ConvertFrom-Json
        foreach ($Key in @(
            "final_status", "final_decision", "underlying_price_before_valid_count",
            "underlying_price_after_valid_count", "injected_underlying_price_count",
            "missing_underlying_price_after_count", "selected_snapshot_path",
            "candidate_generation_allowed", "broker_action_allowed", "official_adoption_allowed"
        )) {
            Write-Output "$Key=$($Summary.$Key)"
        }
    } catch {
        Write-Output "final_status=UNREADABLE_SUMMARY"
        Write-Output "final_decision=UNREADABLE_SUMMARY"
    }
}

exit $PythonExit
