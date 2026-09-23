$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$PythonScript = Join-Path $ScriptDir "v20_90_etf_rotation_evidence_builder.py"

Set-Location $RepoRoot

Write-Host "Running V20.90 ETF rotation evidence builder..."
python $PythonScript

if ($LASTEXITCODE -ne 0) {
    throw "V20.90 ETF rotation evidence builder failed with exit code $LASTEXITCODE"
}

Write-Host "PASS_V20_90_ETF_ROTATION_EVIDENCE_BUILDER_WITH_PARTIAL_COVERAGE"
