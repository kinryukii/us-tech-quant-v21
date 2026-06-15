$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$PythonScript = Join-Path $ScriptDir "v20_89_evidence_coverage_matrix.py"

Set-Location $RepoRoot

Write-Host "Running V20.89 evidence coverage matrix..."
python $PythonScript

if ($LASTEXITCODE -ne 0) {
    throw "V20.89 evidence coverage matrix failed with exit code $LASTEXITCODE"
}

Write-Host "V20.89 evidence coverage matrix complete."
