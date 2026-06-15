$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_108_r8_r3_market_regime_exposure_metadata_to_contribution_mapper.py"

Push-Location $RepoRoot
try {
    python $StageScript
}
finally {
    Pop-Location
}
