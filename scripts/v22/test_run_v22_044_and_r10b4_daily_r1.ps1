$ErrorActionPreference='Stop'
$p = Join-Path $PSScriptRoot 'run_v22_044_and_r10b4_daily_r1.ps1'
$text = Get-Content -LiteralPath $p -Raw
$checks = @(
  @{n='calls_v22_044'; ok=$text.Contains('run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1')},
  @{n='calls_r10b4'; ok=$text.Contains('r10b4_a_rawscore_real_forward_stability_ledger.py')},
  @{n='has_pass_gate'; ok=$text.Contains('PASS_V22_044_DAILY_SINGLE_ENTRYPOINT_FROZEN')},
  @{n='has_same_date_gate'; ok=$text.Contains('same_date_comparable_all_strategies')},
  @{n='has_integrity_gate'; ok=$text.Contains('ranking_integrity_pass')},
  @{n='has_skip_gate'; ok=$text.Contains('EXISTING_DAILY_SUMMARY_NOT_ELIGIBLE_FOR_SKIP')},
  @{n='has_duplicate_guard'; ok=$text.Contains('DUPLICATE_DAILY_PROCESS_DETECTED')},
  @{n='writes_one_latest_summary'; ok=$text.Contains('latest_summary.json')},
  @{n='does_not_modify_core'; ok=(-not $text.Contains('Set-Content -LiteralPath $V22044'))},
  @{n='returns_r10b4_failure'; ok=$text.Contains('R10B4_FAILED')}
)
foreach($c in $checks) { if(-not $c.ok) { throw "TEST_FAILED:$($c.n)" }; Write-Output "PASS:$($c.n)" }
