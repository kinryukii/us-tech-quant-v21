$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root
$Timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$Out = "outputs/v21/DAILY_MOOMOO_RESEARCH_CHAIN_$Timestamp"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$steps = New-Object System.Collections.Generic.List[object]
function Add-Step($name, $status, $attempted) {
  $steps.Add([pscustomobject]@{ stage=$name; final_status=$status; attempted=$attempted }) | Out-Null
}
function Read-Json($path) {
  if (Test-Path $path) { return Get-Content $path -Raw | ConvertFrom-Json }
  return $null
}
function Run-Stage($name, $command, $summaryPath, $mandatory=$true) {
  $stageOutput = & powershell -ExecutionPolicy Bypass -File $command 2>&1
  $code = $LASTEXITCODE
  foreach ($line in $stageOutput) { Write-Host $line }
  $summary = Read-Json $summaryPath
  $status = if ($summary) { $summary.final_status } else { "MISSING_SUMMARY" }
  Add-Step $name $status $true
  if ($mandatory -and ($code -ne 0 -or ($status -notlike "PASS*" -and $status -notlike "PARTIAL_PASS*" -and $status -notlike "WARN*"))) {
    return $false
  }
  return $true
}
$continue = $true
$ok = Run-Stage "V21.198" "scripts/v21/run_v21_198_moomoo_data_backbone_and_health_check.ps1" "outputs/v21/V21.198_MOOMOO_DATA_BACKBONE_AND_HEALTH_CHECK/v21_198_summary.json" $true
if (-not $ok) {
  $final = "FAIL_DAILY_MOOMOO_RESEARCH_CHAIN_DATA_SOURCE"
  $decision = "STOPPED_BEFORE_CANONICAL_IMPORT"
  $continue = $false
}
if ($continue) {
  $ok = Run-Stage "V21.199_R4" "scripts/v21/run_v21_199_r4_rate_limited_history_kline_fetch_and_resume.ps1" "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/v21_199_r4_summary.json" $true
  if (-not $ok) {
    $final = "FAIL_DAILY_MOOMOO_RESEARCH_CHAIN_DATA_IMPORT"
    $decision = "STOPPED_BEFORE_STRATEGY_RERUN"
    $continue = $false
  }
}
if ($continue) {
  if (Test-Path "scripts/v21/run_v21_197_final_broad_date_abcde_rerun_after_manual_import.ps1") {
    $ok = Run-Stage "V21.197_ABCDE" "scripts/v21/run_v21_197_final_broad_date_abcde_rerun_after_manual_import.ps1" "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/v21_197_summary.json" $true
    if (-not $ok) {
      $final = "FAIL_DAILY_MOOMOO_RESEARCH_CHAIN_ABCDE"
      $decision = "STOPPED_AFTER_ABCDE_FAILURE"
      $continue = $false
    }
  } else { Add-Step "V21.197_ABCDE" "NOT_AVAILABLE" $false }
}
if ($continue) {
  if (Test-Path "scripts/v21/run_v21_201_dram_moomoo_r4_date_alignment_and_plan_refresh.ps1") {
    $ok = Run-Stage "V21.201_DRAM" "scripts/v21/run_v21_201_dram_moomoo_r4_date_alignment_and_plan_refresh.ps1" "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH/v21_201_summary.json" $true
    if (-not $ok) {
      $final = "FAIL_DAILY_MOOMOO_RESEARCH_CHAIN_DRAM"
      $decision = "STOPPED_AFTER_DRAM_FAILURE"
      $continue = $false
    }
  } else { Add-Step "V21.201_DRAM" "NOT_AVAILABLE" $false }
}
if ($continue) {
  $s199Check = Read-Json "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/v21_199_r4_summary.json"
  $s197Check = Read-Json "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/v21_197_summary.json"
  $s201Check = Read-Json "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH/v21_201_summary.json"
  $r4Date = if ($s199Check) { $s199Check.latest_moomoo_broad_honest_date } else { "" }
  $abcdeDate = if ($s197Check) { $s197Check.target_rerun_date } else { "" }
  $dramDate = if ($s201Check) { $s201Check.latest_plan_date } else { "" }
  if (-not ($r4Date -and $r4Date -eq $abcdeDate -and $r4Date -eq $dramDate)) {
    Add-Step "DATE_ALIGNMENT_R4_ABCDE_DRAM" "FAIL_DAILY_MOOMOO_RESEARCH_CHAIN_DRAM_DATE_MISMATCH" $true
    $final = "FAIL_DAILY_MOOMOO_RESEARCH_CHAIN_DRAM_DATE_MISMATCH"
    $decision = "STOPPED_AFTER_DRAM_DATE_MISMATCH"
    $continue = $false
  }
}
if ($continue) {
  foreach ($candidate in @("scripts/v21/run_v21_173_daily_chain_orchestrator_for_switch_governance.ps1","scripts/v21/run_v21_172_switch_governance_compact_daily_report_r1.ps1")) {
    if (Test-Path $candidate) {
      & powershell -ExecutionPolicy Bypass -File $candidate
      Add-Step (Split-Path $candidate -Leaf) "ATTEMPTED_OPTIONAL" $true
    }
  }
  $final = "PASS_DAILY_MOOMOO_RESEARCH_CHAIN"
  $decision = "MANDATORY_RESEARCH_CHAIN_COMPLETE"
}
$s198 = Read-Json "outputs/v21/V21.198_MOOMOO_DATA_BACKBONE_AND_HEALTH_CHECK/v21_198_summary.json"
$s199 = Read-Json "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/v21_199_r4_summary.json"
$s201 = Read-Json "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH/v21_201_summary.json"
$summary = [pscustomobject]@{
  final_status=$final
  final_decision=$decision
  run_timestamp_utc=$Timestamp
  research_only=$true
  official_adoption_allowed=$false
  broker_action_allowed=$false
  trade_api_called=$false
  opend_reachable=if ($s198) { $s198.opend_reachable } else { $false }
  latest_moomoo_broad_honest_date=if ($s199) { $s199.latest_moomoo_broad_honest_date } else { "" }
  canonical_latest_date_before=if ($s199) { $s199.canonical_latest_date_before } else { "" }
  canonical_latest_date_after=if ($s199) { $s199.canonical_latest_date_after } else { "" }
  dram_latest_date=if ($s199) { $s199.dram_latest_date } else { "" }
  dram_latest_plan_date=if ($s201) { $s201.latest_plan_date } else { "" }
  stages=$steps
}
$summary | ConvertTo-Json -Depth 6 | Set-Content "$Out/daily_chain_summary.json"
$steps | Export-Csv "$Out/latest_data_status.csv" -NoTypeInformation
"$($summary | ConvertTo-Json -Depth 6)" | Set-Content "$Out/daily_chain_report.txt"
if (Test-Path "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH/dram_daily_plan_moomoo_r4.csv") { Copy-Item "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH/dram_daily_plan_moomoo_r4.csv" "$Out/latest_dram_plan_status.csv" -Force }
$top20 = Get-ChildItem outputs/v21 -Recurse -Filter "abcde_top20_summary*.csv" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 1
if ($top20) { Copy-Item $top20.FullName "$Out/latest_abcde_top20_summary.csv" -Force }
Write-Output "final_status=$final"
Write-Output "final_decision=$decision"
Write-Output "broker_action_allowed=false"
if ($final -like "PASS*") { exit 0 }
exit 1
