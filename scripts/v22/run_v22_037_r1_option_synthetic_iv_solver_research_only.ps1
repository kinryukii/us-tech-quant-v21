param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$InputPath = "",
    [string]$OutputRoot = "",
    [double]$RiskFreeRate = 0.045,
    [double]$DividendYield = 0.0,
    [double]$MaxSigma = 5.0,
    [double]$HighVolRetrySigma = 10.0
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_037_r1_option_synthetic_iv_solver_research_only.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

$ArgsList = @(
    $Script,
    "--repo-root", $RepoRoot,
    "--risk-free-rate", $RiskFreeRate,
    "--dividend-yield", $DividendYield,
    "--max-sigma", $MaxSigma,
    "--high-vol-retry-sigma", $HighVolRetrySigma
)
if ($InputPath -ne "") {
    $ArgsList += @("--input-path", $InputPath)
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

$SummaryPath = if ($OutputRoot -ne "") { Join-Path $OutputRoot "v22_037_r1_summary.json" } else { Join-Path $RepoRoot "outputs\v22\V22.037_R1_OPTION_SYNTHETIC_IV_SOLVER_RESEARCH_ONLY\v22_037_r1_summary.json" }
Write-Output "final_summary_path=$SummaryPath"
$SummaryExists = Test-Path $SummaryPath
Write-Output "summary_exists=$SummaryExists"
if ($SummaryExists) {
    try {
        $Summary = Get-Content -Raw -Path $SummaryPath | ConvertFrom-Json
        foreach ($Key in @(
            "final_status", "final_decision", "iv_solved_count", "greeks_solved_count",
            "open_interest_available_count", "open_interest_unavailable_count",
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
