Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $Dir "..\..")
Push-Location $Root
try {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Dir "run_v21_074_r1_entry_threshold_diagnostic.ps1")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python (Join-Path $Dir "v21_074_r2_missed_winner_attribution.py")
    exit $LASTEXITCODE
}
finally { Pop-Location }
