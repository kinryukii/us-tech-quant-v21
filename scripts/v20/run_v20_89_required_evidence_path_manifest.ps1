$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$PythonScript = Join-Path $ScriptDir "v20_89_required_evidence_path_manifest.py"

Set-Location $RepoRoot

Write-Host "Running V20.89 required evidence path manifest..."
python $PythonScript

if ($LASTEXITCODE -ne 0) {
    throw "V20.89 required evidence path manifest failed with exit code $LASTEXITCODE"
}

Write-Host "PASS_V20_89_REQUIRED_EVIDENCE_PATH_MANIFEST_CREATED_WITH_BLOCKERS_ALLOWED"
