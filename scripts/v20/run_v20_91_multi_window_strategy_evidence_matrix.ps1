$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$PythonScript = Join-Path $ScriptDir "v20_91_multi_window_strategy_evidence_matrix.py"

Set-Location $RepoRoot

Write-Host "Running V20.91 multi-window strategy evidence matrix..."
python $PythonScript

if ($LASTEXITCODE -ne 0) {
    throw "V20.91 multi-window strategy evidence matrix failed with exit code $LASTEXITCODE"
}

Write-Host "PASS_V20_91_MULTI_WINDOW_STRATEGY_EVIDENCE_MATRIX_WITH_PARTIAL_COVERAGE"
