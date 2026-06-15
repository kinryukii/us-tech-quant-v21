$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$PythonScript = Join-Path $ScriptDir "v20_92_evidence_blocker_gap_resolver.py"

Set-Location $RepoRoot

Write-Host "Running V20.92 evidence blocker gap resolver..."
python $PythonScript

if ($LASTEXITCODE -ne 0) {
    throw "V20.92 evidence blocker gap resolver failed with exit code $LASTEXITCODE"
}

Write-Host "PASS_V20_92_EVIDENCE_BLOCKER_GAP_RESOLVER_CREATED"
