$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_108_r10_complete_factor_family_score_assembler.py"

Push-Location $RepoRoot
try {
    python $StageScript
}
finally {
    Pop-Location
}
