param(
    [string]$OutputDir = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_111_r2_sector_industry_neutral_counterfactual_diagnostic.py"

Write-Host "STAGE=V21.111-R2_SECTOR_INDUSTRY_NEUTRAL_COUNTERFACTUAL_DIAGNOSTIC"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_ADOPTION_ALLOWED=FALSE"
Write-Host "BROKER_ACTION_ALLOWED=FALSE"

$ArgsList = @($StageScript, "--root", $RepoRoot)
if ($OutputDir) { $ArgsList += @("--output-dir", $OutputDir) }

Push-Location $RepoRoot
try {
    & python @ArgsList
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
