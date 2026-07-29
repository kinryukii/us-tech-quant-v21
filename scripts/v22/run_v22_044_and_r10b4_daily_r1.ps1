[CmdletBinding()]
param(
    [switch]$Execute,
    [switch]$SkipDailyChain,
    [string]$RepoRoot = 'D:\us-tech-quant'
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path $RepoRoot).Path
. (Join-Path $RepoRoot 'scripts\common\storage_paths.ps1')
$Storage = Get-UstqStoragePaths -RepoRoot $RepoRoot
$OuterResult = 'D:\us-tech-quant-results\outputs\v22\V22_044_AND_R10B4_DAILY_R1'
$V22044 = Join-Path $RepoRoot 'scripts\v22\run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1'
$R10B4 = Join-Path $RepoRoot 'scripts\v22\r10b4_a_rawscore_real_forward_stability_ledger.py'
$V22048 = Join-Path $RepoRoot 'scripts\v22\v22_048_real_abcde_source_provenance_and_persistence.py'
$V22050 = Join-Path $RepoRoot 'scripts\v22\v22_050_compact_abcde_production_versioning.py'
$R10C1 = Join-Path $RepoRoot 'scripts\v22\r10c1_abcde_compact_v1_forward_stability_ledger.py'
$V22044Summary = Join-Path $Storage.daily_root 'current\V22.044_DAILY_SINGLE_ENTRYPOINT_FREEZE_AND_GUARD_R1\v22_044_summary.json'

function Write-AtomicJson([hashtable]$Value, [string]$Path) {
    New-Item -ItemType Directory -Force -Path (Split-Path $Path) | Out-Null
    $tmp = "$Path.tmp"
    $Value | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $tmp -Encoding utf8
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}
function Get-Json([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "MISSING_SUMMARY:$Path" }
    return (Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json)
}
function Get-PythonPath {
    $venv = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venv) { return $venv }
    return 'python'
}
function Test-DuplicateDailyProcess {
    $selfPid = $PID
    $needles = @('run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1','r10b4_a_rawscore_real_forward_stability_ledger.py','run_v22_044_and_r10b4_daily_r1.ps1')
    $matches = @(Get-CimInstance Win32_Process | Where-Object {
        $_.ProcessId -ne $selfPid -and $_.CommandLine -and ($needles | Where-Object { $_.CommandLine -like "*$_*" })
    })
    return $matches.Count -gt 0
}

$summary = @{
    final_status='FAIL'; final_decision='UNINITIALIZED';
    v22_044_command="& '$V22044' -Execute"; v22_044_exit_code=$null;
    r10b4_command="$(Get-PythonPath) '$R10B4' --update-and-report"; r10b4_executed=$false; r10b4_exit_code=$null;
    v22_044_core_entrypoint_modified=$false; v22_040_core_entrypoint_modified=$false;
    duplicate_daily_process_detected=$false; skip_daily_chain=[bool]$SkipDailyChain
}
try {
    if (-not $Execute) { throw 'EXECUTE_SWITCH_REQUIRED' }
    if (Test-DuplicateDailyProcess) { $summary.duplicate_daily_process_detected=$true; throw 'DUPLICATE_DAILY_PROCESS_DETECTED' }
    if (-not $SkipDailyChain) {
        & $V22044 -Execute -RepoRoot $RepoRoot
        $summary.v22_044_exit_code = $LASTEXITCODE
    } else { $summary.v22_044_exit_code = 0 }
    $v = Get-Json $V22044Summary
    $summary.v22_044_final_status = [string]$v.final_status
    $summary.v22_044_canonical_latest_date = [string]$v.canonical_latest_date
    $summary.v22_044_abcde_latest_date = [string]$v.abcde_latest_date
    $summary.v22_044_same_date_comparable = [bool]$v.same_date_comparable_all_strategies
    # Current V22.044 emits hard_gate_passed rather than a separate ranking field.
    $ranking = if ($null -ne $v.ranking_integrity_pass) { [bool]$v.ranking_integrity_pass } else { [bool]$v.hard_gate_passed }
    $summary.v22_044_ranking_integrity_pass = $ranking
    $eligible = $summary.v22_044_exit_code -eq 0 -and $summary.v22_044_final_status -eq 'PASS_V22_044_DAILY_SINGLE_ENTRYPOINT_FROZEN' -and $summary.v22_044_same_date_comparable -and $ranking
    if ($SkipDailyChain -and -not ($eligible -and $summary.v22_044_abcde_latest_date -eq $summary.v22_044_canonical_latest_date)) { throw 'EXISTING_DAILY_SUMMARY_NOT_ELIGIBLE_FOR_SKIP' }
    if (-not $eligible) { throw 'V22_044_FAILED_R10B4_NOT_EXECUTED' }
    $python = Get-PythonPath
    # Compact output is versioned into its own history; it never enters Legacy R10B4.
    & $python $V22050
    $summary.v22_050_exit_code=$LASTEXITCODE
    if ($LASTEXITCODE -ne 0) { throw 'COMPACT_VERSIONING_FAILED' }
    & $python $R10C1
    $summary.compact_r10c1_executed=$true; $summary.compact_r10c1_exit_code=$LASTEXITCODE
    if ($LASTEXITCODE -ne 0) { throw 'COMPACT_R10C1_FAILED' }
    $summary.legacy_r10b4_executed=$false
    $summary.active_forward_ledger='R10C1_ABCDE_COMPACT_V1'
    $summary.real_abcde_available=$false; $summary.real_abcde_eligible=$false
    $summary.final_status='PASS'; $summary.final_decision='INSUFFICIENT_COMPACT_FORWARD_DATA'
    $summary.result_directory=$OuterResult; $summary.latest_summary_path=(Join-Path $OuterResult 'latest_summary.json')
    Write-AtomicJson $summary $summary.latest_summary_path
    $summary | ConvertTo-Json -Depth 8; exit 0
    & $python $R10B4 --update-and-report
    $summary.r10b4_executed=$true; $summary.r10b4_exit_code=$LASTEXITCODE
    if ($LASTEXITCODE -ne 0) { throw 'R10B4_FAILED' }
    $rpath='D:\us-tech-quant-results\outputs\v22\R10B4_A_RAWSCORE_REAL_FORWARD_STABILITY_LEDGER_R1\summary.json'
    $raudit='D:\us-tech-quant-results\outputs\v22\R10B4_A_RAWSCORE_REAL_FORWARD_STABILITY_LEDGER_R1\ledger_update_audit.json'
    $r=Get-Json $rpath; $a=Get-Json $raudit
    $summary.r10b4_final_status=[string]$r.final_status; $summary.r10b4_final_decision=[string]$r.final_decision
    foreach($k in @('new_signal_date_count','new_signal_row_count','immutable_signal_row_conflict_count','immutable_signal_date_conflict_count')) { $summary[$k]=$a.$k }
    $summary.newly_matured_5d_count=$a.newly_matured.'5'; $summary.newly_matured_10d_count=$a.newly_matured.'10'; $summary.newly_matured_20d_count=$a.newly_matured.'20'
    $summary.final_status='PASS'; $summary.final_decision=[string]$r.final_decision
} catch {
    $reason=$_.Exception.Message
    if ($reason -eq 'DUPLICATE_DAILY_PROCESS_DETECTED') { $summary.final_decision=$reason }
    elseif ($reason -eq 'EXISTING_DAILY_SUMMARY_NOT_ELIGIBLE_FOR_SKIP') { $summary.final_decision=$reason }
    elseif ($reason -eq 'V22_044_FAILED_R10B4_NOT_EXECUTED') { $summary.final_decision=$reason }
    elseif ($reason -eq 'REAL_ABCDE_UNAVAILABLE_R10B4_NOT_EXECUTED') { $summary.final_decision=$reason }
    elseif ($reason -eq 'R10B4_FAILED') { $summary.final_decision='R10B4_FAILED' }
    else { $summary.final_decision="OUTER_ORCHESTRATOR_ERROR:$reason" }
}
$summary.result_directory=$OuterResult; $summary.latest_summary_path=(Join-Path $OuterResult 'latest_summary.json')
Write-AtomicJson $summary $summary.latest_summary_path
$summary | ConvertTo-Json -Depth 8
if ($summary.final_status -ne 'PASS') { exit 1 }
exit 0
