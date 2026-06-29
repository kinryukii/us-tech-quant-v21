param(
    [string]$OutputDir = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_111_r3_exposure_adjusted_alpha_retention_diagnostic.py"
$SummaryPath = Join-Path $RepoRoot "outputs\v21\V21.111_R3_EXPOSURE_ADJUSTED_ALPHA_RETENTION_DIAGNOSTIC\V21.111_R3_EXPOSURE_ADJUSTED_ALPHA_RETENTION_DIAGNOSTIC_summary.json"

Write-Host "STAGE=V21.111-R3_EXPOSURE_ADJUSTED_ALPHA_RETENTION_DIAGNOSTIC"
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
        Write-Host ("OUTPUT_DIR=" + $Summary.output_dir)
        Write-Host ("BEST_VARIANT_ID=" + $Summary.best_variant_id)
        Write-Host ("BEST_VARIANT_CLASSIFICATION=" + $Summary.best_variant_classification)
        Write-Host ("BEST_TOP20_OVERLAP_WITH_RAW=" + $Summary.best_top20_overlap_with_raw)
        Write-Host ("BEST_TOP50_OVERLAP_WITH_RAW=" + $Summary.best_top50_overlap_with_raw)
    }
    exit 0
}
finally {
    Pop-Location
}
