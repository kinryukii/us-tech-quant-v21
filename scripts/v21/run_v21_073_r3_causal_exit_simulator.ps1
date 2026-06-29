Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
Push-Location $RepoRoot
try {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ScriptDir "run_v21_073_r2_price_path_integrity_audit.ps1")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python (Join-Path $ScriptDir "v21_073_r3_causal_exit_simulator.py")
    exit $LASTEXITCODE
}
finally { Pop-Location }
