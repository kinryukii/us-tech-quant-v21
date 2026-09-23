$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$PythonScript = Join-Path $ScriptDir "v20_93_evidence_schema_repair_pack.py"

Set-Location $RepoRoot

Write-Host "Running V20.93 evidence schema repair pack..."
python $PythonScript

if ($LASTEXITCODE -ne 0) {
    throw "V20.93 evidence schema repair pack failed with exit code $LASTEXITCODE"
}

Write-Host "PASS_V20_93_EVIDENCE_SCHEMA_REPAIR_PACK_CREATED_WITH_PARTIAL_REPAIRS_ALLOWED"
