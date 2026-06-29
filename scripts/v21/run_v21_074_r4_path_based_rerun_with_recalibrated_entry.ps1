Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $Dir "..\..")
$Validation = Join-Path $Root "outputs\v21\v21_074\V21_074_R4_VALIDATION_SUMMARY.csv"
Push-Location $Root
try {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Dir "run_v21_074_r3_soft_entry_gate_recalibration.ps1")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python (Join-Path $Dir "v21_074_r4_path_based_rerun_with_recalibrated_entry.py")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $Row = Import-Csv $Validation | Select-Object -First 1
    Write-Host "VALIDATION_SUMMARY=$Validation"
    Write-Host "FINAL_STATUS=$($Row.final_status)"
    Write-Host "DECISION=$($Row.decision)"
    Write-Host "BEST_TOP20=$($Row.best_top20_recalibrated_policy)"
    Write-Host "BEST_TOP50=$($Row.best_top50_recalibrated_policy)"
    Write-Host "MISSED_WINNERS_BEFORE/AFTER=$($Row.missed_winners_before)/$($Row.missed_winners_after)"
    exit 0
}
finally { Pop-Location }
