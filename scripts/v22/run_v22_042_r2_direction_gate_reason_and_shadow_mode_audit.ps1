param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant",
    [bool]$UseV22041Latest = $true,
    [bool]$RequireQQQConfirmation = $true,
    [bool]$RequireSPYConfirmation = $false,
    [bool]$EnableShadowModes = $true
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_042_r2_direction_gate_reason_and_shadow_mode_audit.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$SummaryPath = Join-Path $RepoRoot "outputs\v22\V22.042_R2_DIRECTION_GATE_REASON_AND_SHADOW_MODE_AUDIT\v22_042_r2_summary.json"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$ArgsList = @($Script, "--repo-root", $RepoRoot)
if ($Execute) { $ArgsList += "--execute" }
if (-not $UseV22041Latest) { $ArgsList += "--no-use-v22-041-latest" }
if (-not $RequireQQQConfirmation) { $ArgsList += "--no-require-qqq-confirmation" }
if ($RequireSPYConfirmation) { $ArgsList += "--require-spy-confirmation" }
if (-not $EnableShadowModes) { $ArgsList += "--disable-shadow-modes" }

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
            "final_status", "final_decision", "v22_041_liquidity_candidate_count",
            "soxx_direction_label", "qqq_confirmation_label", "spy_confirmation_label",
            "strict_official_final_direction_label", "strict_official_promoted_candidate_count",
            "semiconductor_only_shadow_direction_label", "semiconductor_only_shadow_candidate_count",
            "relaxed_broad_shadow_direction_label", "relaxed_broad_shadow_candidate_count",
            "primary_wait_reason_code", "broker_action_allowed", "official_adoption_allowed"
        )) {
            Write-Output "$Key=$($Summary.$Key)"
        }
    } catch {
        Write-Output "final_status=UNREADABLE_SUMMARY"
        Write-Output "final_decision=UNREADABLE_SUMMARY"
    }
}

exit $PythonExit
