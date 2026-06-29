param(
    [string]$OutputDir = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_111_r4_d_exposure_dependency_decomposition.py"
$SummaryPath = Join-Path $RepoRoot "outputs\v21\V21.111_R4_D_EXPOSURE_DEPENDENCY_DECOMPOSITION\V21.111_R4_D_EXPOSURE_DEPENDENCY_DECOMPOSITION_summary.json"

Write-Host "STAGE=V21.111-R4_D_EXPOSURE_DEPENDENCY_DECOMPOSITION"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_ADOPTION_ALLOWED=FALSE"
Write-Host "BROKER_ACTION_ALLOWED=FALSE"

$ArgsList = @($StageScript, "--root", $RepoRoot)
if ($OutputDir) { $ArgsList += @("--output-dir", $OutputDir) }

Push-Location $RepoRoot
try {
    & python @ArgsList
    $ExitCode = $LASTEXITCODE
    if ($ExitCode -ne 0) { exit $ExitCode }
    if (Test-Path $SummaryPath) {
        $Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
        Write-Host ("FINAL_STATUS=" + $Summary.final_status)
        Write-Host ("DECISION=" + $Summary.decision)
        Write-Host ("DEPENDENCY_CLASSIFICATION=" + $Summary.dependency_classification)
        Write-Host ("EXPOSURE_ONLY_COMBINED_TOP20_OVERLAP=" + $Summary.exposure_only_combined_top20_overlap)
        Write-Host ("EXPOSURE_ONLY_COMBINED_TOP50_OVERLAP=" + $Summary.exposure_only_combined_top50_overlap)
        Write-Host ("EXPOSURE_ONLY_COMBINED_SPEARMAN_CORR=" + $Summary.exposure_only_combined_spearman_corr)
        Write-Host ("RESIDUAL_COMBINED_TOP20_OVERLAP=" + $Summary.residual_combined_top20_overlap)
        Write-Host ("RESIDUAL_COMBINED_TOP50_OVERLAP=" + $Summary.residual_combined_top50_overlap)
        Write-Host ("FORWARD_DATA_AVAILABLE=" + $Summary.forward_data_available)
        Write-Host ("OUTPUT_DIR=" + $Summary.output_dir)
    }
    exit 0
}
finally {
    Pop-Location
}
