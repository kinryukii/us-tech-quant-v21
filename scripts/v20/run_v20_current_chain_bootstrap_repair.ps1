param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$RepairDir = Join-Path $RepoRoot "outputs\v20\repair"
$Consolidation = Join-Path $RepoRoot "outputs\v20\consolidation"
$ReadCenter = Join-Path $RepoRoot "outputs\v20\read_center"
$Ops = Join-Path $RepoRoot "outputs\v20\ops"
New-Item -ItemType Directory -Force -Path $RepairDir | Out-Null

$SummaryPath = Join-Path $RepairDir "V20_CURRENT_CHAIN_BOOTSTRAP_REPAIR_SUMMARY.md"
$StatusPath = Join-Path $RepairDir "V20_CURRENT_CHAIN_BOOTSTRAP_REPAIR_STATUS.csv"
$MatrixPath = Join-Path $RepairDir "V20_CURRENT_CHAIN_DEPENDENCY_MATRIX.csv"
$LaneStatusPath = Join-Path $RepairDir "V20_CURRENT_CHAIN_LANE_STATUS.csv"
$CurrentLaneStatusPath = Join-Path $RepairDir "V20_CURRENT_DAILY_RESEARCH_LANE_STATUS.csv"
$ForwardLaneStatusPath = Join-Path $RepairDir "V20_FORWARD_OUTCOME_VALIDATION_LANE_STATUS.csv"
$ConclusionPath = Join-Path $ReadCenter "V20_CURRENT_DAILY_CONCLUSION.md"

function RelPath([string]$Path) {
    try {
        return (Resolve-Path $Path).Path.Replace($RepoRoot.Path, "").TrimStart("\").Replace("\", "/")
    }
    catch {
        return $Path.Replace($RepoRoot.Path, "").TrimStart("\").Replace("\", "/")
    }
}

function Read-FirstCsvRowResult([string]$Path) {
    $result = [pscustomobject]@{
        status = "OK"
        row = $null
    }
    if (-not (Test-Path $Path)) {
        $result.status = "MISSING_FILE"
        return $result
    }
    if ([System.IO.Path]::GetExtension($Path) -ine ".csv") {
        $result.status = "NON_CSV_FILE"
        return $result
    }
    if ((Get-Item $Path).Length -eq 0) {
        $result.status = "EMPTY_FILE"
        return $result
    }
    $firstLine = Get-Content -Path $Path -TotalCount 1
    if ($null -eq $firstLine -or [string]::IsNullOrWhiteSpace([string]$firstLine)) {
        $result.status = "MALFORMED_CSV_HEADER_EMPTY"
        return $result
    }
    $header = [string]$firstLine
    if ($header.StartsWith(",") -or $header.EndsWith(",") -or $header.Contains(",,")) {
        $result.status = "MALFORMED_CSV_HEADER"
        return $result
    }
    $rows = @(Import-Csv -Path $Path)
    if ($rows.Count -eq 0) {
        $result.status = "EMPTY_CSV"
        return $result
    }
    $result.row = $rows[0]
    return $result
}

function Read-FirstCsvRow([string]$Path) {
    $result = Read-FirstCsvRowResult $Path
    return $result.row
}

function Get-FieldValue([object]$Row, [string]$Field) {
    if ($null -eq $Row -or [string]::IsNullOrWhiteSpace($Field)) {
        return ""
    }
    $prop = $Row.PSObject.Properties | Where-Object { $_.Name -ieq $Field } | Select-Object -First 1
    if ($null -eq $prop) {
        return ""
    }
    return [string]$prop.Value
}

function Test-NonEmpty([string]$Path) {
    return (Test-Path $Path) -and ((Get-Item $Path).Length -gt 0)
}

function Add-DependencyRow(
    [System.Collections.Generic.List[object]]$Rows,
    [string]$Stage,
    [string]$RequiredBy,
    [string]$RequiredFile,
    [string]$RequiredStatusField,
    [string]$ExpectedValue
) {
    $exists = Test-Path $RequiredFile
    $nonEmpty = Test-NonEmpty $RequiredFile
    $row = $null
    $actual = ""
    $sourceStatus = "FILE_EXISTS_ONLY"
    if (-not [string]::IsNullOrWhiteSpace($RequiredStatusField)) {
        $readResult = Read-FirstCsvRowResult $RequiredFile
        $sourceStatus = $readResult.status
        $row = $readResult.row
        $actual = Get-FieldValue $row $RequiredStatusField
    }
    $blocked = ""
    if (-not $exists) {
        $blocked = "missing_required_file"
    }
    elseif (-not $nonEmpty) {
        $blocked = "empty_required_file"
    }
    elseif ($RequiredStatusField -and $sourceStatus -ne "OK") {
        $blocked = $sourceStatus
    }
    elseif ($RequiredStatusField -and $ExpectedValue -and ($actual -ne $ExpectedValue)) {
        $blocked = "field_value_mismatch"
    }
    $Rows.Add([pscustomobject]@{
        stage = $Stage
        required_by = $RequiredBy
        required_file = (RelPath $RequiredFile)
        required_file_exists = if ($exists) { "TRUE" } else { "FALSE" }
        required_file_non_empty = if ($nonEmpty) { "TRUE" } else { "FALSE" }
        required_status_field = $RequiredStatusField
        expected_value = $ExpectedValue
        actual_value = $actual
        source_status = $sourceStatus
        blocker_reason = $blocked
    })
}

function Write-DependencyMatrix {
    $rows = [System.Collections.Generic.List[object]]::new()
    $c = $Consolidation
    $o = $Ops
    $r = $ReadCenter

    Add-DependencyRow $rows "V16_SECOND_STAGE_UNIVERSE" "V18.13B" "$($RepoRoot.Path)\configs\v16\universe\us_full_second_stage_generated.yaml" "" ""
    Add-DependencyRow $rows "V18_CURRENT_RAW105_FACTOR_PACK_REPAIR" "V18.13B" "$($RepoRoot.Path)\outputs\v18\factor_pack\V18_CURRENT_RAW105_FACTOR_PACK_RANKING_REPAIR_STATUS.csv" "STATUS" "PASS_V18_CURRENT_RAW105_FACTOR_PACK_REPAIR"
    Add-DependencyRow $rows "V18_CURRENT_FACTOR_PACK" "V18.13B" "$($RepoRoot.Path)\outputs\v18\factor_pack\V18_CURRENT_RAW105_FACTOR_PACK_RANKING.csv" "" ""
    Add-DependencyRow $rows "V18_CURRENT_TECHNICAL_TIMING_REPAIR" "V18.13B" "$($RepoRoot.Path)\outputs\v18\technical_timing\V18_6A_CURRENT_TECHNICAL_TIMING_REPAIR_STATUS.csv" "STATUS" "PASS_V18_CURRENT_TECHNICAL_TIMING_REPAIR"
    Add-DependencyRow $rows "V18_CURRENT_TECHNICAL_TIMING" "V18.13B" "$($RepoRoot.Path)\outputs\v18\technical_timing\V18_6A_CURRENT_TECHNICAL_TIMING.csv" "" ""
    Add-DependencyRow $rows "V18.13B" "V18.16A" "$($RepoRoot.Path)\outputs\v18\candidates\V18_13B_CURRENT_RANKED_CANDIDATES.csv" "" ""
    Add-DependencyRow $rows "V18_CURRENT_RANKED_CANDIDATES_ALIAS_REPAIR" "V18.16A" "$($RepoRoot.Path)\outputs\v18\candidates\V18_CURRENT_RANKED_CANDIDATES_ALIAS_STATUS.csv" "alias_status" "WARN_ALIAS_CREATED_FROM_PARTIAL_V18_13B"
    Add-DependencyRow $rows "V18.13B/V18_CURRENT_ALIAS" "V18.16A" "$($RepoRoot.Path)\outputs\v18\candidates\V18_CURRENT_RANKED_CANDIDATES.csv" "" ""
    Add-DependencyRow $rows "V18_MANUAL_UNIVERSE_ADDITIONS_REPAIR" "V18.16A" "$($RepoRoot.Path)\outputs\v18\universe\V18_MANUAL_UNIVERSE_ADDITIONS_REPAIR_STATUS.csv" "" ""
    Add-DependencyRow $rows "V18_MANUAL_UNIVERSE_ADDITIONS" "V18.16A" "$($RepoRoot.Path)\state\v18\universe\V18_MANUAL_UNIVERSE_ADDITIONS.csv" "" ""
    Add-DependencyRow $rows "V18.16A" "V18.35D" "$($RepoRoot.Path)\state\v18\universe\V18_UNIVERSE_ROLLING_STATE.csv" "" ""
    Add-DependencyRow $rows "V18.16A" "V18.35D" "$($RepoRoot.Path)\outputs\v18\universe\V18_CURRENT_UNIVERSE_ROLLING_STATE.csv" "" ""
    Add-DependencyRow $rows "V18.35D_FULL_RANKED_CANDIDATES_REPAIR" "V20.7V" "$($RepoRoot.Path)\outputs\v18\candidates\V18_CURRENT_FULL_RANKED_CANDIDATES_REPAIR_STATUS.csv" "" ""
    Add-DependencyRow $rows "V18.35D" "V20.7V" "$($RepoRoot.Path)\outputs\v18\candidates\V18_CURRENT_FULL_RANKED_CANDIDATES.csv" "" ""
    Add-DependencyRow $rows "V18.35D" "V20.7V" "$($RepoRoot.Path)\outputs\v18\ops\V18_35D_READ_FIRST.txt" "" ""
    Add-DependencyRow $rows "V20.46" "V20.47" "$c\V20_46_NEXT_STEP_DECISION.csv" "decision" "PASS_READY_FOR_CONTROLLED_CURRENT_MARKET_REFRESH_STAGE"
    Add-DependencyRow $rows "V20.47" "POST_REFRESH_RECOMPUTE" "$c\V20_47_NEXT_STEP_DECISION.csv" "decision" "PASS_CONTROLLED_REFRESH_CERTIFIED_FOR_RESEARCH_HANDOFF"
    Add-DependencyRow $rows "POST_REFRESH_RECOMPUTE" "V20.7V" "$c\V20_POST_REFRESH_RECOMPUTE_STATUS.csv" "status" "PASS_V20_POST_REFRESH_RECOMPUTE_HANDOFF_COMPLETED"
    Add-DependencyRow $rows "V20.7V" "V20.7W" "$c\V20_7V_VALIDATION_SUMMARY.csv" "status" "PASS_V20_7V_ACTIVE_MARKET_SOURCE_STAGING_READY"
    Add-DependencyRow $rows "V20.7W" "V20.7X" "$c\V20_7W_GATE_DECISION.csv" "status" "PASS_V20_7W_ACTIVE_MARKET_SOURCE_CERTIFICATION_READY"
    Add-DependencyRow $rows "V20.7X" "V20.8" "$c\V20_7X_GATE_DECISION.csv" "status" "PASS_V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING_READY"
    Add-DependencyRow $rows "V20.8" "V20.9" "$c\V20_8_GATE_DECISION.csv" "status" "PASS_V20_8_NORMALIZED_RESEARCH_DATASET_CONSTRUCTED"
    Add-DependencyRow $rows "V20.9" "V20.10" "$c\V20_9_GATE_DECISION.csv" "status" "PASS_V20_9_FACTOR_RESEARCH_DATASET_PREPARED"
    Add-DependencyRow $rows "V20.10" "V20.11" "$c\V20_10_GATE_DECISION.csv" "status" "PASS_V20_10_FACTOR_SOURCE_ATTACHMENT_OR_AVAILABILITY_AUDIT"
    Add-DependencyRow $rows "V20.11" "V20.12" "$c\V20_11_GATE_DECISION.csv" "status" "PASS_V20_11_FACTOR_SOURCE_ATTACHMENT_PLAN_OR_FIRST_ATTACHABLE_FACTOR_LAYER"
    Add-DependencyRow $rows "V20.12" "V20.13" "$c\V20_12_GATE_DECISION.csv" "STATUS" "PASS_V20_12_FACTOR_INPUT_LAYER_REVIEW_OR_FACTOR_EVIDENCE_GATE"
    Add-DependencyRow $rows "V20.13" "V20.14" "$c\V20_13_GATE_DECISION.csv" "STATUS" "PASS_V20_13_FIRST_LIMITED_FACTOR_EVIDENCE_LAYER"
    Add-DependencyRow $rows "V20.14" "V20.15" "$c\V20_14_GATE_DECISION.csv" "STATUS" "PASS_V20_14_FACTOR_EVIDENCE_REVIEW_OR_FACTOR_SCORE_GATE"
    Add-DependencyRow $rows "V20.15" "V20.16" "$c\V20_15_GATE_DECISION.csv" "READY_FOR_V20_16_FACTOR_SCORE_REVIEW_OR_BACKTEST_READINESS_GATE_NEXT" "TRUE"
    Add-DependencyRow $rows "V20.16" "V20.17" "$c\V20_16_GATE_DECISION.csv" "READY_FOR_V20_17_BACKTEST_INPUT_OUTCOME_AND_BENCHMARK_PREPARATION_NEXT" "TRUE"
    Add-DependencyRow $rows "V20.17" "V20.18/V20.26" "$c\V20_17_BACKTEST_INPUT_CANDIDATE_DATASET.csv" "" ""
    Add-DependencyRow $rows "V20.17" "V20.18" "$c\V20_17_GATE_DECISION.csv" "STATUS" "PASS_V20_17_BACKTEST_INPUT_OUTCOME_AND_BENCHMARK_PREPARATION"
    Add-DependencyRow $rows "V20.18" "V20.19" "$c\V20_18_GATE_DECISION.csv" "STATUS" "PASS_V20_18_OUTCOME_BENCHMARK_SOURCE_ATTACHMENT_OR_BACKTEST_READINESS_REVIEW"
    Add-DependencyRow $rows "V20.19" "V20.20" "$c\V20_19_GATE_DECISION.csv" "STATUS" "PASS_V20_19_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_OR_BLOCKER_RESOLUTION"
    Add-DependencyRow $rows "V20.20" "V20.21" "$c\V20_20_GATE_DECISION.csv" "STATUS" "PASS_V20_20_OUTCOME_BENCHMARK_SOURCE_CERTIFICATION_OR_BLOCKER_RESOLUTION"
    Add-DependencyRow $rows "V20.21" "V20.22" "$c\V20_21_GATE_DECISION.csv" "STATUS" "PASS_V20_21_OUTCOME_BENCHMARK_INPUT_STAGING_AND_REGISTRATION"
    Add-DependencyRow $rows "V20.22" "V20.23" "$c\V20_22_GATE_DECISION.csv" "STATUS" "PASS_V20_22_OUTCOME_BENCHMARK_INPUT_CERTIFICATION_RETRY"
    Add-DependencyRow $rows "V20.23" "V20.24" "$c\V20_23_GATE_DECISION.csv" "STATUS" "PASS_V20_23_OUTCOME_BENCHMARK_INPUT_SOURCE_CREATION_OR_STAGING_FROM_ALLOWED_LOCAL_DATA"
    Add-DependencyRow $rows "V20.24" "V20.25" "$c\V20_24_GATE_DECISION.csv" "STATUS" "PASS_V20_24_LOCAL_OUTCOME_BENCHMARK_DATA_REQUIREMENT_AND_ACQUISITION_PLAN"
    Add-DependencyRow $rows "V20.25" "V20.26" "$c\V20_25_GATE_DECISION.csv" "STATUS" "PASS_V20_25_LOCAL_OUTCOME_BENCHMARK_IMPORTER_OR_MANUAL_STAGING"
    Add-DependencyRow $rows "V20.26" "V20.27" "$c\V20_26_GATE_DECISION.csv" "READY_FOR_V20_27_YAHOO_CACHE_CERTIFICATION_NEXT" "TRUE"
    Add-DependencyRow $rows "V20.26" "V20.34/V20.35-R1" "$c\V20_26_REQUIRED_SYMBOL_UNIVERSE.csv" "" ""
    Add-DependencyRow $rows "V20.27" "V20.28" "$c\V20_27_GATE_DECISION.csv" "READY_FOR_V20_28_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_RETRY_NEXT" "TRUE"
    Add-DependencyRow $rows "V20.28" "V20.29" "$c\V20_28_GATE_DECISION.csv" "READY_FOR_V20_29_FIRST_LIMITED_BACKTEST_READINESS_GATE_NEXT" "TRUE"
    Add-DependencyRow $rows "V20.29" "V20.30" "$c\V20_29_GATE_DECISION.csv" "READY_FOR_V20_30_FIRST_LIMITED_BACKTEST_EXECUTION_NEXT" "TRUE"
    Add-DependencyRow $rows "V20.30" "V20.31" "$c\V20_30_GATE_DECISION.csv" "STATUS" "PASS_V20_30_FIRST_LIMITED_BACKTEST_EXECUTION"
    Add-DependencyRow $rows "V20.31" "V20.32" "$c\V20_31_GATE_DECISION.csv" "READY_FOR_V20_32_FIRST_LIMITED_BACKTEST_EXECUTION_RETRY_NEXT" "TRUE"
    Add-DependencyRow $rows "V20.32" "V20.33" "$c\V20_32_GATE_DECISION.csv" "READY_FOR_V20_33_FIRST_LIMITED_BACKTEST_RESULT_REVIEW_AND_SANITY_CHECK_NEXT" "TRUE"
    Add-DependencyRow $rows "V20.33" "V20.34" "$c\V20_33_GATE_DECISION.csv" "READY_FOR_V20_34_EXPANDED_BACKTEST_WINDOW_OR_MULTI_SIGNAL_REVIEW_NEXT" "TRUE"
    Add-DependencyRow $rows "V20.34" "V20.35" "$c\V20_34_RANDOM_ASOF_TOP20_PREFLIGHT_DECISION.csv" "ready_for_v20_35_random_asof_top20_technical_recompute_backtest" "TRUE"
    Add-DependencyRow $rows "V20.34" "V20.35" "$o\V20_34_READ_FIRST.txt" "" ""
    Add-DependencyRow $rows "V20.35" "V20.35-R1" "$c\V20_35_NEXT_STEP_DECISION_SUMMARY.csv" "STATUS" "BLOCKED_V20_35_RANDOM_ASOF_TOP20_TECHNICAL_RECOMPUTE_BACKTEST"
    Add-DependencyRow $rows "V20.35-R1" "V20.35-R2" "$c\V20_35_R1_NEXT_STEP_DECISION_SUMMARY.csv" "READY_FOR_V20_35_RETRY_RANDOM_ASOF_TOP20_TECHNICAL_RECOMPUTE_BACKTEST" "TRUE"
    Add-DependencyRow $rows "V20.35-R2" "V20.36/V20.42" "$c\V20_35_R2_NEXT_STEP_DECISION_SUMMARY.csv" "READY_FOR_V20_36_ENTRY_STRATEGY_MATRIX_DESIGN" "TRUE"
    Add-DependencyRow $rows "V20.35-R2" "V20.42" "$c\V20_35_R2_ASOF_TOP20_SELECTIONS.csv" "" ""
    Add-DependencyRow $rows "V20.36" "V20.37" "$c\V20_36_NEXT_STEP_DECISION_SUMMARY.csv" "READY_FOR_V20_37_ENTRY_STRATEGY_BACKTEST_EXECUTION" "TRUE"
    Add-DependencyRow $rows "V20.37" "V20.38/V20.39-R2" "$c\V20_37_NEXT_STEP_DECISION_SUMMARY.csv" "READY_FOR_FACTOR_EFFECTIVENESS_ABLATION_AUDIT" "TRUE"
    Add-DependencyRow $rows "V20.38" "V20.39" "$c\V20_38_NEXT_STEP_DECISION_SUMMARY.csv" "READY_FOR_SHADOW_DYNAMIC_WEIGHTING_DESIGN" "TRUE"
    Add-DependencyRow $rows "V20.39" "V20.39-R1" "$c\V20_39_NEXT_STEP_DECISION_SUMMARY.csv" "READY_FOR_SHADOW_WEIGHTED_RECOMPUTE_BACKTEST" "TRUE"
    Add-DependencyRow $rows "V20.39-R1" "V20.39-R2" "$c\V20_39_R1_NEXT_STEP_DECISION_SUMMARY.csv" "READY_FOR_SHADOW_WEIGHTED_ENTRY_STRATEGY_BACKTEST" "TRUE"
    Add-DependencyRow $rows "V20.39-R2" "V20.40" "$c\V20_39_R2_NEXT_STEP_DECISION_SUMMARY.csv" "READY_FOR_V20_40_PORTFOLIO_LEVEL_EXPLORATORY_BACKTEST" "TRUE"
    Add-DependencyRow $rows "V20.40" "V20.41/V20.42" "$c\V20_40_NEXT_STEP_DECISION_SUMMARY.csv" "READY_FOR_DAILY_OPERATOR_RESEARCH_REPORT_DESIGN" "TRUE"
    Add-DependencyRow $rows "V20.41" "V20.42" "$c\V20_41_NEXT_STEP_DECISION_SUMMARY.csv" "STATUS" "PASS_V20_41_RESEARCH_FACTOR_PIT_EXPANSION_PLAN"
    Add-DependencyRow $rows "V20.42" "V20.43" "$c\V20_42_DAILY_OPERATOR_REPORT_NEXT_STEP_DECISION.csv" "STATUS" "PASS_V20_42_DAILY_OPERATOR_RESEARCH_REPORT_DESIGN"
    Add-DependencyRow $rows "V20.43" "V20.44/V20.45" "$c\V20_43_DAILY_OPERATOR_REPORT_NEXT_STEP_DECISION.csv" "STATUS" "PASS_V20_43_DAILY_OPERATOR_REPORT_DRY_RUN"
    Add-DependencyRow $rows "V20.44" "V20.45" "$c\V20_44_CURRENT_RUN_READINESS_DECISION.csv" "decision" "PASS_DAILY_OPERATOR_REPORT_ACCEPTED_FOR_CURRENT_RESEARCH_RUN"
    Add-DependencyRow $rows "V20.45" "V20.46" "$c\V20_45_CURRENT_OPERATOR_NEXT_STEP_DECISION.csv" "decision" "PASS_RESEARCH_ONLY_CURRENT_OPERATOR_REPORT_CREATED"
    Add-DependencyRow $rows "V20.47" "V20.55" "$c\V20_47_NEXT_STEP_DECISION.csv" "decision" "PASS_CONTROLLED_REFRESH_CERTIFIED_FOR_RESEARCH_HANDOFF"
    Add-DependencyRow $rows "V20.52" "V20.55" "$c\V20_52_NEXT_STEP_DECISION.csv" "STATUS" "PASS_V20_52_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_GATE"
    Add-DependencyRow $rows "V20.53" "V20.55" "$c\V20_53_NEXT_STEP_DECISION.csv" "STATUS" "PASS_V20_53_OFFICIAL_RECOMMENDATION_SCHEMA_DRY_RUN_GATE"
    Add-DependencyRow $rows "V20.54" "V20.55" "$r\V20_CURRENT_USER_READABLE_CURRENT_DECISION_REPORT.md" "" ""
    Add-DependencyRow $rows "V20.55" "operator" "$c\V20_55_DAILY_ONE_CLICK_RUN_SUMMARY.csv" "overall_status" "PASS_V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER"

    $rows | Export-Csv -Path $MatrixPath -NoTypeInformation
}

function Get-BlockerFromMatrix {
    if (-not (Test-Path $MatrixPath)) {
        return "dependency_matrix_missing"
    }
    $rows = Import-Csv -Path $MatrixPath
    $bad = $rows | Where-Object { $_.blocker_reason -ne "" } | Select-Object -First 1
    if ($null -eq $bad) {
        return ""
    }
    return "$($bad.stage) -> $($bad.required_by): $($bad.required_file) $($bad.blocker_reason) expected=$($bad.expected_value) actual=$($bad.actual_value)"
}

function Get-ForwardOutcomeGapSummary {
    $gapPath = Join-Path $Consolidation "V20_27_REQUIRED_ACTIVE_INPUT_GAP_ANALYSIS.csv"
    $out = @{
        pending_forward_target_dates = "FALSE"
        latest_available_cache_date = ""
        first_required_target_date = ""
        latest_required_target_date = ""
        blocker_reason = ""
    }
    if (-not (Test-Path $gapPath)) {
        $out.blocker_reason = "V20.27 gap analysis missing."
        return $out
    }
    $rows = @(Import-Csv -Path $gapPath)
    if ($rows.Count -eq 0) {
        $out.blocker_reason = "V20.27 gap analysis empty."
        return $out
    }
    $rootCauses = @()
    $latestCacheDates = @()
    $firstTargets = @()
    $latestTargets = @()
    foreach ($row in $rows) {
        $root = Get-FieldValue $row "root_cause"
        if ($root) { $rootCauses += $root }
        $latestCache = Get-FieldValue $row "latest_available_cache_price_date"
        if ($latestCache) { $latestCacheDates += $latestCache }
        $firstTarget = Get-FieldValue $row "first_required_target_date"
        if ($firstTarget) { $firstTargets += $firstTarget }
        $latestTarget = Get-FieldValue $row "latest_required_target_date"
        if ($latestTarget) { $latestTargets += $latestTarget }
    }
    $pending = ($rootCauses -contains "PIT_SAFE_FORWARD_OUTCOME_TARGET_DATES_NOT_AVAILABLE") -or ($rootCauses -contains "PIT_SAFE_FORWARD_BENCHMARK_TARGET_DATES_NOT_AVAILABLE")
    $out.pending_forward_target_dates = if ($pending) { "TRUE" } else { "FALSE" }
    $out.latest_available_cache_date = if ($latestCacheDates.Count -gt 0) { ($latestCacheDates | Sort-Object | Select-Object -Last 1) } else { "" }
    $out.first_required_target_date = if ($firstTargets.Count -gt 0) { ($firstTargets | Sort-Object | Select-Object -First 1) } else { "" }
    $out.latest_required_target_date = if ($latestTargets.Count -gt 0) { ($latestTargets | Sort-Object | Select-Object -Last 1) } else { "" }
    $out.blocker_reason = ($rootCauses | Sort-Object -Unique) -join ";"
    return $out
}

function Write-LaneStatusFiles(
    [string]$CurrentLaneStatus,
    [string]$CurrentFirstFailedStage,
    [string]$CurrentBlockerReason,
    [string]$ForwardLaneStatus,
    [string]$ForwardFirstFailedStage,
    [string]$ForwardBlockerReason,
    [hashtable]$ForwardGap
) {
    $currentRow = [pscustomobject]@{
        lane_name = "CURRENT_DAILY_RESEARCH_LANE"
        lane_status = $CurrentLaneStatus
        first_failed_stage = $CurrentFirstFailedStage
        blocker_reason = $CurrentBlockerReason
        handoff_allowed = if ($CurrentLaneStatus -in @("PASS", "WARN")) { "TRUE" } else { "FALSE" }
        research_only_allowed = if ($CurrentLaneStatus -in @("PASS", "WARN")) { "TRUE" } else { "FALSE" }
        official_promotion_allowed = "FALSE"
        official_recommendation_created = "FALSE"
        weight_mutated = "FALSE"
        trade_action_created = "FALSE"
        pending_forward_target_dates = $ForwardGap.pending_forward_target_dates
        latest_available_cache_date = $ForwardGap.latest_available_cache_date
        first_required_target_date = $ForwardGap.first_required_target_date
        latest_required_target_date = $ForwardGap.latest_required_target_date
    }
    $forwardRow = [pscustomobject]@{
        lane_name = "FORWARD_OUTCOME_VALIDATION_LANE"
        lane_status = $ForwardLaneStatus
        first_failed_stage = $ForwardFirstFailedStage
        blocker_reason = $ForwardBlockerReason
        handoff_allowed = "FALSE"
        research_only_allowed = "FALSE"
        official_promotion_allowed = "FALSE"
        official_recommendation_created = "FALSE"
        weight_mutated = "FALSE"
        trade_action_created = "FALSE"
        pending_forward_target_dates = $ForwardGap.pending_forward_target_dates
        latest_available_cache_date = $ForwardGap.latest_available_cache_date
        first_required_target_date = $ForwardGap.first_required_target_date
        latest_required_target_date = $ForwardGap.latest_required_target_date
    }
    @($currentRow) | Export-Csv -Path $CurrentLaneStatusPath -NoTypeInformation
    @($forwardRow) | Export-Csv -Path $ForwardLaneStatusPath -NoTypeInformation
    @($currentRow, $forwardRow) | Export-Csv -Path $LaneStatusPath -NoTypeInformation
}

function Read-KeyValueCsv([string]$Path) {
    $out = @{}
    if (-not (Test-Path $Path)) {
        return $out
    }
    foreach ($row in @(Import-Csv -Path $Path)) {
        $key = Get-FieldValue $row "metric"
        $value = Get-FieldValue $row "value"
        if ($key) {
            $out[$key] = $value
            continue
        }
        $key = Get-FieldValue $row "key"
        $value = Get-FieldValue $row "value"
        if ($key) {
            $out[$key] = $value
        }
    }
    return $out
}

function Get-TopRankingNames {
    $aliasStatusRow = Read-FirstCsvRow (Join-Path $RepoRoot "outputs\v18\candidates\V18_CURRENT_RANKED_CANDIDATES_ALIAS_STATUS.csv")
    $aliasStatus = Get-FieldValue $aliasStatusRow "alias_status"
    $aliasRowCount = Get-FieldValue $aliasStatusRow "row_count"
    $candidates = @(
        (Join-Path $RepoRoot "outputs\v18\candidates\V18_CURRENT_FULL_RANKED_CANDIDATES.csv"),
        (Join-Path $RepoRoot "outputs\v18\candidates\V18_CURRENT_RANKED_CANDIDATES.csv")
    )
    foreach ($path in $candidates) {
        if (-not (Test-NonEmpty $path)) {
            continue
        }
        $rows = @(Import-Csv -Path $path | Select-Object -First 10)
        if ($rows.Count -eq 0) {
            continue
        }
        $items = @()
        foreach ($row in $rows) {
            $ticker = Get-FieldValue $row "ticker"
            $name = Get-FieldValue $row "name"
            $rank = Get-FieldValue $row "rank"
            if ($ticker) {
                $prefix = if ($rank) { "#$rank " } else { "" }
                $suffix = if ($name -and $name -ne $ticker) { " ($name)" } else { "" }
                $items += "$prefix$ticker$suffix"
            }
        }
        if ($items.Count -gt 0) {
            $isFull = $path -like "*V18_CURRENT_FULL_RANKED_CANDIDATES.csv"
            $repairRow = Read-FirstCsvRow (Join-Path $RepoRoot "outputs\v18\candidates\V18_CURRENT_FULL_RANKED_CANDIDATES_REPAIR_STATUS.csv")
            $repairStatus = Get-FieldValue $repairRow "repair_status"
            $repairCount = Get-FieldValue $repairRow "output_row_count"
            $prefix = if ($isFull -and $repairStatus) {
                "Available from outputs/v18/candidates/V18_CURRENT_FULL_RANKED_CANDIDATES.csv; status=$repairStatus; row_count=$repairCount; top ranked: "
            } elseif ($aliasStatus) {
                "Available from outputs/v18/candidates/V18_CURRENT_RANKED_CANDIDATES.csv; status=$aliasStatus; row_count=$aliasRowCount; top ranked: "
            } else { "" }
            return ($prefix + ($items -join ", "))
        }
    }
    $summaryRow = Read-FirstCsvRow (Join-Path $RepoRoot "outputs\v18\read_center\V18_13B_CURRENT_RANKED_CANDIDATE_SUMMARY.csv")
    $summaryStatus = Get-FieldValue $summaryRow "STATUS"
    $rankSourceStatus = Get-FieldValue $summaryRow "RANK_SOURCE_STATUS"
    if ($summaryStatus -eq "OK_V18_13B_RANKED_CANDIDATE_READ_CENTER_READY" -and $rankSourceStatus -ne "NO_SCORE_SOURCE_FOUND") {
        $path = Join-Path $RepoRoot "outputs\v18\candidates\V18_13B_CURRENT_RANKED_CANDIDATES.csv"
        if (Test-NonEmpty $path) {
            $rows = @(Import-Csv -Path $path | Select-Object -First 10)
            $items = @()
            foreach ($row in $rows) {
                $ticker = Get-FieldValue $row "ticker"
                $rank = Get-FieldValue $row "rank"
                if ($ticker) {
                    $prefix = if ($rank) { "#$rank " } else { "" }
                    $items += "$prefix$ticker"
                }
            }
            if ($items.Count -gt 0) {
                return ($items -join ", ")
            }
        }
    }
    return "Not available from an authoritative current ranking artifact."
}

function Get-FullRankingHandoffText {
    $path = Join-Path $RepoRoot "outputs\v18\candidates\V18_CURRENT_FULL_RANKED_CANDIDATES.csv"
    $statusRow = Read-FirstCsvRow (Join-Path $RepoRoot "outputs\v18\candidates\V18_CURRENT_FULL_RANKED_CANDIDATES_REPAIR_STATUS.csv")
    $status = Get-FieldValue $statusRow "repair_status"
    $rowCount = Get-FieldValue $statusRow "output_row_count"
    $source = Get-FieldValue $statusRow "source_file"
    if (Test-NonEmpty $path) {
        return "Available from outputs/v18/candidates/V18_CURRENT_FULL_RANKED_CANDIDATES.csv; status=$status; row_count=$rowCount; source=$source."
    }
    return "Not available from outputs/v18/candidates/V18_CURRENT_FULL_RANKED_CANDIDATES.csv."
}

function Get-V20SevenVText {
    $row = Read-FirstCsvRow (Join-Path $Consolidation "V20_7V_VALIDATION_SUMMARY.csv")
    if ($null -eq $row) {
        return "V20.7V status: not available."
    }
    $status = Get-FieldValue $row "status"
    $expected = Get-FieldValue $row "expected_market_date"
    $dist = Get-FieldValue $row "staging_latest_price_date_distribution"
    $missing = Get-FieldValue $row "missing_core_field_summary"
    $stale = Get-FieldValue $row "stale_ticker_count"
    $missingPrice = Get-FieldValue $row "missing_latest_price_count"
    $usable = Get-FieldValue $row "active_source_staging_candidate_ready"
    $eligible = Get-FieldValue $row "eligible_row_count"
    $excluded = Get-FieldValue $row "excluded_row_count"
    $excludedExamples = Get-FieldValue $row "excluded_ticker_examples"
    $quarantine = Get-FieldValue $row "v20_7v_used_quarantine"
    $excludedPath = Join-Path $Consolidation "V20_7V_EXCLUDED_TICKERS.csv"
    $excludedRows = if (Test-Path $excludedPath) { @(Import-Csv -Path $excludedPath) } else { @() }
    $excludedReasons = (($excludedRows | Select-Object -First 10 | ForEach-Object { "$(Get-FieldValue $_ "ticker"):$(Get-FieldValue $_ "exclusion_reason")" }) -join "; ")
    return @"
V20.7V status: $status
expected_market_date: $expected
observed price date distribution: $dist
stale_ticker_count: $stale
missing_latest_price_count: $missingPrice
missing core field summary: $missing
active market source staging usable: $usable
active_market_source_staging_usable: $usable
eligible_row_count: $eligible
excluded_row_count: $excluded
excluded ticker examples: $excludedExamples
excluded ticker reasons: $excludedReasons
v20_7v_used_quarantine: $quarantine
"@
}

function Get-V20SevenVMode {
    $row = Read-FirstCsvRow (Join-Path $Consolidation "V20_7V_VALIDATION_SUMMARY.csv")
    $status = Get-FieldValue $row "status"
    $usable = Get-FieldValue $row "active_source_staging_candidate_ready"
    if ($status -eq "PASS_V20_7V_ACTIVE_MARKET_SOURCE_STAGING_READY" -and $usable -eq "TRUE") {
        $v49Research = Read-FirstCsvRow (Join-Path $Consolidation "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv")
        $v49Promotion = Read-FirstCsvRow (Join-Path $Consolidation "V20_49_OFFICIAL_PROMOTION_GATE.csv")
        if ((Get-FieldValue $v49Research "research_only_gate_status") -eq "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE" -and
            (Get-FieldValue $v49Promotion "official_promotion_gate_status") -ne "PASS_V20_49_OPERATOR_REVIEW_ACCEPTANCE_GATE") {
            return "RESEARCH_ONLY_DAILY_CONCLUSION_READY_OFFICIAL_PROMOTION_BLOCKED"
        }
        return "PASS_RESEARCH_ONLY"
    }
    return "DEGRADED_RESEARCH_ONLY_DUE_TO_STALE_MARKET_DATA"
}

function Get-PostRefreshText {
    $row = Read-FirstCsvRow (Join-Path $Consolidation "V20_POST_REFRESH_RECOMPUTE_STATUS.csv")
    if ($null -eq $row) {
        return "post_refresh_recompute_ran: FALSE"
    }
    $status = Get-FieldValue $row "status"
    $pre = Get-FieldValue $row "pre_refresh_cache_latest_date_distribution"
    $post = Get-FieldValue $row "post_refresh_cache_latest_date_distribution"
    $full = Get-FieldValue $row "post_refresh_full_ranked_latest_price_date_distribution"
    $v7v = Get-FieldValue $row "v20_7v_status_after_post_refresh"
    $usable = Get-FieldValue $row "active_market_source_staging_usable"
    $missing = Get-FieldValue $row "missing_required_core_field_summary"
    $eligible = Get-FieldValue $row "eligible_row_count"
    $excluded = Get-FieldValue $row "excluded_row_count"
    $excludedExamples = Get-FieldValue $row "excluded_ticker_examples"
    $quarantine = Get-FieldValue $row "v20_7v_used_quarantine"
    return @"
post_refresh_recompute_ran: TRUE
post_refresh_status: $status
pre_refresh_cache_latest_date_distribution: $pre
post_refresh_cache_latest_date_distribution: $post
post_refresh_full_ranked_latest_price_date_distribution: $full
v20_7v_status_after_post_refresh: $v7v
active_market_source_staging_usable_after_post_refresh: $usable
eligible_row_count_after_post_refresh: $eligible
excluded_row_count_after_post_refresh: $excluded
excluded_ticker_examples_after_post_refresh: $excludedExamples
v20_7v_used_quarantine_after_post_refresh: $quarantine
missing_required_core_field_summary_after_post_refresh: $missing
"@
}

function Get-MarketRefreshText {
    $row = Read-FirstCsvRow (Join-Path $Consolidation "V20_47_CONTROLLED_REFRESH_SUMMARY.csv")
    if ($null -eq $row) {
        return "V20.47 status: not available."
    }
    $status = Get-FieldValue $row "certification_status"
    $requested = Get-FieldValue $row "requested_ticker_count"
    $success = Get-FieldValue $row "success_count"
    $empty = Get-FieldValue $row "empty_dataframe_count"
    $exceptions = Get-FieldValue $row "exception_count"
    $provider = Get-FieldValue $row "provider_available"
    $dominant = Get-FieldValue $row "dominant_failure_reason"
    $cacheStatus = if ($success -and $success -ne "0") { "succeeded_or_partial" } else { "blocked" }
    return @"
V20.47 status: $status
requested ticker count: $requested
success count: $success
empty dataframe count: $empty
exception count: $exceptions
provider_available: $provider
provider/cache refresh status: $cacheStatus
dominant failure reason: $dominant
stale-data blocker remains: $(if ((Get-V20SevenVMode) -eq "DEGRADED_RESEARCH_ONLY_DUE_TO_STALE_MARKET_DATA") { "TRUE" } else { "FALSE" })
"@
}

function Get-V20SixteenText {
    $row = Read-FirstCsvRow (Join-Path $Consolidation "V20_16_GATE_DECISION.csv")
    $diag = Read-FirstCsvRow (Join-Path $Consolidation "V20_16_GATE_DECISION_DIAGNOSTICS.csv")
    if ($null -eq $row) {
        return "V20.16 gate decision: not available."
    }
    $decision = Get-FieldValue $row "v20_16_gate_decision"
    $status = Get-FieldValue $row "v20_16_status"
    if (-not $status) { $status = Get-FieldValue $row "STATUS" }
    $failed = Get-FieldValue $row "failed_condition_list"
    $consumed = Get-FieldValue $row "consumed_current_v20_7v_outputs"
    $eligible = Get-FieldValue $row "eligible_row_count"
    $excluded = Get-FieldValue $row "excluded_row_count"
    $expected = Get-FieldValue $row "expected_score_rows_from_current_v20_7v_eligible_rows"
    $reviewed = Get-FieldValue $row "FACTOR_SCORE_ROWS_REVIEWED"
    $recommended = Get-FieldValue $diag "recommended_next_action"
    return @"
V20.16 gate decision: $decision
V20.16 status: $status
V20.16 consumed current V20.7V outputs: $consumed
V20.16 eligible_row_count: $eligible
V20.16 excluded_row_count: $excluded
V20.16 expected score rows: $expected
V20.16 factor score rows reviewed: $reviewed
V20.16 failed condition list: $failed
V20.16 recommended_next_action: $recommended
"@
}

function Get-V20SeventeenText {
    $row = Read-FirstCsvRow (Join-Path $Consolidation "V20_17_GATE_DECISION.csv")
    $diag = Read-FirstCsvRow (Join-Path $Consolidation "V20_17_GATE_DECISION_DIAGNOSTICS.csv")
    if ($null -eq $row) {
        return "V20.17 status: not available."
    }
    $decision = Get-FieldValue $row "v20_17_gate_decision"
    $status = Get-FieldValue $row "v20_17_status"
    if (-not $status) { $status = Get-FieldValue $row "STATUS" }
    $failed = Get-FieldValue $row "failed_condition_list"
    $candidateRows = Get-FieldValue $row "prepared_candidate_input_rows"
    $benchmarkRows = Get-FieldValue $row "prepared_benchmark_rows"
    $outcomeRows = Get-FieldValue $row "outcome_rows_available"
    $consumedV7v = Get-FieldValue $row "consumed_current_v20_7v_active_staging"
    $recommended = Get-FieldValue $diag "recommended_next_action"
    return @"
V20.17 gate decision: $decision
V20.17 status: $status
V20.17 consumed current V20.7V active staging: $consumedV7v
V20.17 prepared candidate input rows: $candidateRows
V20.17 prepared benchmark rows: $benchmarkRows
V20.17 outcome rows available: $outcomeRows
V20.17 failed condition list: $failed
V20.17 recommended_next_action: $recommended
"@
}

function Get-LatestRunId {
    $paths = @(
        (Join-Path $Consolidation "V20_55_DAILY_ONE_CLICK_RUN_SUMMARY.csv"),
        (Join-Path $Consolidation "V20_47_CONTROLLED_REFRESH_SUMMARY.csv")
    )
    foreach ($path in $paths) {
        $row = Read-FirstCsvRow $path
        $runId = Get-FieldValue $row "run_id"
        if ($runId) {
            return $runId
        }
    }
    return ""
}

function Write-DailyConclusion([string]$FinalStatus, [string]$FirstFailedStage, [string]$BlockerReason, [string]$V55Status) {
    New-Item -ItemType Directory -Force -Path $ReadCenter | Out-Null
    $latestRunId = Get-LatestRunId
    $v55Conclusion = if ($V55Status -eq "PASS_V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER") { "PASS" } elseif ($V55Status -eq "WARN_V20_55_RESEARCH_ONLY_READY_PROMOTION_BLOCKED") { "WARN" } elseif ($V55Status) { "BLOCKED" } else { "NOT_RUN_OR_UNAVAILABLE" }
    $dailyMode = Get-V20SevenVMode
    $topRanking = Get-TopRankingNames
    $fullRanking = Get-FullRankingHandoffText
    $v20SevenV = Get-V20SevenVText
    $marketRefresh = Get-MarketRefreshText
    $v20Sixteen = Get-V20SixteenText
    $v20Seventeen = Get-V20SeventeenText
    $postRefresh = Get-PostRefreshText
    $technicalPath = Join-Path $RepoRoot "outputs\v18\technical_timing\V18_6A_CURRENT_TECHNICAL_TIMING.csv"
    $buyZone = if (Test-NonEmpty $technicalPath) { "Available from outputs/v18/technical_timing/V18_6A_CURRENT_TECHNICAL_TIMING.csv." } else { "Not available from the current technical timing artifact." }
    $manualStatusRow = Read-FirstCsvRow (Join-Path $RepoRoot "outputs\v18\universe\V18_MANUAL_UNIVERSE_ADDITIONS_REPAIR_STATUS.csv")
    $manualCount = Get-FieldValue $manualStatusRow "manual_addition_row_count"
    if (-not $manualCount) { $manualCount = "not available" }
    $blockerText = if ($FinalStatus -eq "PASS") { "None reported by bootstrap repair." } else { "$FirstFailedStage - $BlockerReason" }
$text = @"
# V20 Current Daily Conclusion

## Executive Status

final_chain_status: $FinalStatus
v20_55_status: $v55Conclusion
daily_conclusion_mode: $dailyMode
latest_valid_run_id: $latestRunId
first_failed_stage: $FirstFailedStage
blocker_reason: $BlockerReason

## Data Freshness / Market Source

$v20SevenV

## Market Refresh Diagnostics

$marketRefresh

## Post-Refresh Recompute

$postRefresh

## V20.16 Gate Decision

$v20Sixteen

## V20.17 Backtest Input Preparation

$v20Seventeen

## Current Ranking

$topRanking

## Full Ranking / V18.35D Handoff

$fullRanking

## Technical Timing / Buy-Zone

$buyZone

## Research Conclusion

No active-market daily recommendation is allowed unless V20.7V active market source staging is usable. This conclusion is research-only when market data is stale or partially ranked.

## Manual Additions

manual_addition_count: $manualCount

## Remaining Blockers

$blockerText

## Safety

This is research-only. There is no broker execution, no official recommendation, no trade action, no official ranking mutation, and no factor weight mutation. No buy/sell/hold instruction is created.
"@
    Set-Content -Path $ConclusionPath -Value $text -Encoding UTF8
}

function Resolve-StageWrapper([object]$Stage) {
    $repoCandidate = Join-Path $RepoRoot $Stage.Wrapper
    if (Test-Path $repoCandidate) {
        return $repoCandidate
    }
    return (Join-Path $ScriptDir $Stage.Wrapper)
}

function Invoke-CheckedStage([object]$Stage) {
    $wrapper = Resolve-StageWrapper $Stage
    if (-not (Test-Path $wrapper)) {
        return [pscustomobject]@{
            stage = $Stage.Name
            wrapper = $Stage.Wrapper
            exit_code = 127
            status = "MISSING_WRAPPER"
            passed = "FALSE"
            blocker_reason = "missing_wrapper"
        }
    }

    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $stageArgs = @()
        if ($Stage.PSObject.Properties.Name -contains "Args") {
            $stageArgs = @($Stage.Args)
        }
        $output = & powershell -NoProfile -ExecutionPolicy Bypass -File $wrapper @stageArgs 2>&1
        $exit = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    $statusRow = Read-FirstCsvRow (Join-Path $RepoRoot $Stage.StatusFile)
    $actual = Get-FieldValue $statusRow $Stage.StatusField
    if (-not $actual) {
        $statusMatch = $output | Select-String -Pattern "^(STATUS=|STATUS: )(.+)$" | Select-Object -Last 1
        if ($null -ne $statusMatch -and $statusMatch.Matches.Count -gt 0) {
            $actual = $statusMatch.Matches[0].Groups[2].Value
        }
    }
    $allowedWarning = ($Stage.ExpectedStatus -eq "") -and ($actual -like "WARN_*")
    $passes = (($exit -eq 0) -and (($Stage.ExpectedStatus -eq "") -or ($actual -eq $Stage.ExpectedStatus))) -or $allowedWarning
    $reason = ""
    if (-not $passes) {
        $reason = "exit_code=$exit expected_status=$($Stage.ExpectedStatus) actual_status=$actual"
    }
    return [pscustomobject]@{
        stage = $Stage.Name
        wrapper = $Stage.Wrapper
        exit_code = $exit
        status = $actual
        passed = if ($passes) { "TRUE" } else { "FALSE" }
        blocker_reason = $reason
    }
}

$stages = @(
    [pscustomobject]@{ Name="V16_SECOND_STAGE_UNIVERSE"; Wrapper="scripts\v16\run_v16_second_stage_universe_bootstrap_repair.ps1"; StatusFile="outputs\v16\universe\V16_SECOND_STAGE_UNIVERSE_REPAIR_STATUS.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V16_SECOND_STAGE_UNIVERSE_REPAIR" },
    [pscustomobject]@{ Name="V18_CURRENT_RAW105_FACTOR_PACK_REPAIR"; Wrapper="scripts\v18\run_v18_current_raw105_factor_pack_repair.ps1"; StatusFile="outputs\v18\factor_pack\V18_CURRENT_RAW105_FACTOR_PACK_RANKING_REPAIR_STATUS.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V18_CURRENT_RAW105_FACTOR_PACK_REPAIR" },
    [pscustomobject]@{ Name="V18_CURRENT_TECHNICAL_TIMING_REPAIR"; Wrapper="scripts\v18\run_v18_current_technical_timing_repair.ps1"; StatusFile="outputs\v18\technical_timing\V18_6A_CURRENT_TECHNICAL_TIMING_REPAIR_STATUS.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V18_CURRENT_TECHNICAL_TIMING_REPAIR" },
    [pscustomobject]@{ Name="V18.13B"; Wrapper="scripts\v18\run_v18_13B_ranked_candidate_read_center.ps1"; StatusFile="outputs\v18\read_center\V18_13B_CURRENT_RANKED_CANDIDATE_SUMMARY.csv"; StatusField="STATUS"; ExpectedStatus="" },
    [pscustomobject]@{ Name="V18_CURRENT_RANKED_CANDIDATES_ALIAS_REPAIR"; Wrapper="scripts\v18\run_v18_current_ranked_candidates_alias_repair.ps1"; StatusFile="outputs\v18\candidates\V18_CURRENT_RANKED_CANDIDATES_ALIAS_STATUS.csv"; StatusField="alias_status"; ExpectedStatus="WARN_ALIAS_CREATED_FROM_PARTIAL_V18_13B" },
    [pscustomobject]@{ Name="V18_MANUAL_UNIVERSE_ADDITIONS_REPAIR"; Wrapper="scripts\v18\run_v18_manual_universe_additions_repair.ps1"; StatusFile="outputs\v18\universe\V18_MANUAL_UNIVERSE_ADDITIONS_REPAIR_STATUS.csv"; StatusField="STATUS"; ExpectedStatus="" },
    [pscustomobject]@{ Name="V18.16A"; Wrapper="scripts\v18\run_v18_16A_universe_rolling_state_builder.ps1"; Args=@("-Root", $RepoRoot.Path); StatusFile="outputs\v18\ops\V18_16A_READ_FIRST.txt"; StatusField="STATUS"; ExpectedStatus="" },
    [pscustomobject]@{ Name="V18.35D_FULL_RANKED_CANDIDATES_REPAIR"; Wrapper="scripts\v18\run_v18_current_full_ranked_candidates_repair.ps1"; StatusFile="outputs\v18\candidates\V18_CURRENT_FULL_RANKED_CANDIDATES_REPAIR_STATUS.csv"; StatusField="repair_status"; ExpectedStatus="" },
    [pscustomobject]@{ Name="V20.46"; Wrapper="run_v20_46_current_market_refresh_readiness_gate.ps1"; StatusFile="outputs\v20\consolidation\V20_46_NEXT_STEP_DECISION.csv"; StatusField="decision"; ExpectedStatus="PASS_READY_FOR_CONTROLLED_CURRENT_MARKET_REFRESH_STAGE" },
    [pscustomobject]@{ Name="V20.47"; Wrapper="run_v20_47_controlled_current_market_refresh_and_cache_certification.ps1"; StatusFile="outputs\v20\consolidation\V20_47_NEXT_STEP_DECISION.csv"; StatusField="decision"; ExpectedStatus="PASS_CONTROLLED_REFRESH_CERTIFIED_FOR_RESEARCH_HANDOFF" },
    [pscustomobject]@{ Name="V20_POST_REFRESH_RECOMPUTE"; Wrapper="run_v20_post_refresh_recompute_handoff.ps1"; StatusFile="outputs\v20\consolidation\V20_POST_REFRESH_RECOMPUTE_STATUS.csv"; StatusField="status"; ExpectedStatus="PASS_V20_POST_REFRESH_RECOMPUTE_HANDOFF_COMPLETED" },
    [pscustomobject]@{ Name="V20.7V"; Wrapper="run_v20_7v_active_market_source_staging_from_accepted_v18_result.ps1"; StatusFile="outputs\v20\consolidation\V20_7V_VALIDATION_SUMMARY.csv"; StatusField="status"; ExpectedStatus="PASS_V20_7V_ACTIVE_MARKET_SOURCE_STAGING_READY" },
    [pscustomobject]@{ Name="V20.7W"; Wrapper="run_v20_7w_active_market_source_certification_retry_from_v20_7v_staging.ps1"; StatusFile="outputs\v20\consolidation\V20_7W_GATE_DECISION.csv"; StatusField="status"; ExpectedStatus="PASS_V20_7W_ACTIVE_MARKET_SOURCE_CERTIFICATION_READY" },
    [pscustomobject]@{ Name="V20.7X"; Wrapper="run_v20_7x_active_market_input_lineage_binding_retry_from_certified_v20_7w_source.ps1"; StatusFile="outputs\v20\consolidation\V20_7X_GATE_DECISION.csv"; StatusField="status"; ExpectedStatus="PASS_V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING_READY" },
    [pscustomobject]@{ Name="V20.8"; Wrapper="run_v20_8_normalized_research_dataset_construction.ps1"; StatusFile="outputs\v20\consolidation\V20_8_GATE_DECISION.csv"; StatusField="status"; ExpectedStatus="PASS_V20_8_NORMALIZED_RESEARCH_DATASET_CONSTRUCTED" },
    [pscustomobject]@{ Name="V20.9"; Wrapper="run_v20_9_factor_research_dataset_preparation.ps1"; StatusFile="outputs\v20\consolidation\V20_9_GATE_DECISION.csv"; StatusField="status"; ExpectedStatus="PASS_V20_9_FACTOR_RESEARCH_DATASET_PREPARED" },
    [pscustomobject]@{ Name="V20.10"; Wrapper="run_v20_10_factor_source_attachment_or_availability_audit.ps1"; StatusFile="outputs\v20\consolidation\V20_10_GATE_DECISION.csv"; StatusField="status"; ExpectedStatus="PASS_V20_10_FACTOR_SOURCE_ATTACHMENT_OR_AVAILABILITY_AUDIT" },
    [pscustomobject]@{ Name="V20.11"; Wrapper="run_v20_11_factor_source_attachment_plan_or_first_attachable_factor_layer.ps1"; StatusFile="outputs\v20\consolidation\V20_11_GATE_DECISION.csv"; StatusField="status"; ExpectedStatus="PASS_V20_11_FACTOR_SOURCE_ATTACHMENT_PLAN_OR_FIRST_ATTACHABLE_FACTOR_LAYER" },
    [pscustomobject]@{ Name="V20.12"; Wrapper="run_v20_12_factor_input_layer_review_or_factor_evidence_gate.ps1"; StatusFile="outputs\v20\consolidation\V20_12_GATE_DECISION.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_12_FACTOR_INPUT_LAYER_REVIEW_OR_FACTOR_EVIDENCE_GATE" },
    [pscustomobject]@{ Name="V20.13"; Wrapper="run_v20_13_first_limited_factor_evidence_layer.ps1"; StatusFile="outputs\v20\consolidation\V20_13_GATE_DECISION.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_13_FIRST_LIMITED_FACTOR_EVIDENCE_LAYER" },
    [pscustomobject]@{ Name="V20.14"; Wrapper="run_v20_14_factor_evidence_review_or_factor_score_gate.ps1"; StatusFile="outputs\v20\consolidation\V20_14_GATE_DECISION.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_14_FACTOR_EVIDENCE_REVIEW_OR_FACTOR_SCORE_GATE" },
    [pscustomobject]@{ Name="V20.15"; Wrapper="run_v20_15_first_limited_factor_score_layer.ps1"; StatusFile="outputs\v20\consolidation\V20_15_GATE_DECISION.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_15_FIRST_LIMITED_FACTOR_SCORE_LAYER" },
    [pscustomobject]@{ Name="V20.16"; Wrapper="run_v20_16_factor_score_review_or_backtest_readiness_gate.ps1"; StatusFile="outputs\v20\consolidation\V20_16_GATE_DECISION.csv"; StatusField="READY_FOR_V20_17_BACKTEST_INPUT_OUTCOME_AND_BENCHMARK_PREPARATION_NEXT"; ExpectedStatus="TRUE" },
    [pscustomobject]@{ Name="V20.17"; Wrapper="run_v20_17_backtest_input_outcome_and_benchmark_preparation.ps1"; StatusFile="outputs\v20\consolidation\V20_17_GATE_DECISION.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_17_BACKTEST_INPUT_OUTCOME_AND_BENCHMARK_PREPARATION" },
    [pscustomobject]@{ Name="V20.18"; Wrapper="run_v20_18_outcome_benchmark_source_attachment_or_backtest_readiness_review.ps1"; StatusFile="outputs\v20\consolidation\V20_18_GATE_DECISION.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_18_OUTCOME_BENCHMARK_SOURCE_ATTACHMENT_OR_BACKTEST_READINESS_REVIEW" },
    [pscustomobject]@{ Name="V20.19"; Wrapper="run_v20_19_outcome_benchmark_value_attachment_or_blocker_resolution.ps1"; StatusFile="outputs\v20\consolidation\V20_19_GATE_DECISION.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_19_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_OR_BLOCKER_RESOLUTION" },
    [pscustomobject]@{ Name="V20.20"; Wrapper="run_v20_20_outcome_benchmark_source_certification_or_blocker_resolution.ps1"; StatusFile="outputs\v20\consolidation\V20_20_GATE_DECISION.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_20_OUTCOME_BENCHMARK_SOURCE_CERTIFICATION_OR_BLOCKER_RESOLUTION" },
    [pscustomobject]@{ Name="V20.21"; Wrapper="run_v20_21_outcome_benchmark_input_staging_and_registration.ps1"; StatusFile="outputs\v20\consolidation\V20_21_GATE_DECISION.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_21_OUTCOME_BENCHMARK_INPUT_STAGING_AND_REGISTRATION" },
    [pscustomobject]@{ Name="V20.22"; Wrapper="run_v20_22_outcome_benchmark_input_certification_retry.ps1"; StatusFile="outputs\v20\consolidation\V20_22_GATE_DECISION.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_22_OUTCOME_BENCHMARK_INPUT_CERTIFICATION_RETRY" },
    [pscustomobject]@{ Name="V20.23"; Wrapper="run_v20_23_outcome_benchmark_input_source_creation_or_staging_from_allowed_local_data.ps1"; StatusFile="outputs\v20\consolidation\V20_23_GATE_DECISION.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_23_OUTCOME_BENCHMARK_INPUT_SOURCE_CREATION_OR_STAGING_FROM_ALLOWED_LOCAL_DATA" },
    [pscustomobject]@{ Name="V20.24"; Wrapper="run_v20_24_local_outcome_benchmark_data_requirement_and_acquisition_plan.ps1"; StatusFile="outputs\v20\consolidation\V20_24_GATE_DECISION.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_24_LOCAL_OUTCOME_BENCHMARK_DATA_REQUIREMENT_AND_ACQUISITION_PLAN" },
    [pscustomobject]@{ Name="V20.25"; Wrapper="run_v20_25_local_outcome_benchmark_importer_or_manual_staging.ps1"; StatusFile="outputs\v20\consolidation\V20_25_GATE_DECISION.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_25_LOCAL_OUTCOME_BENCHMARK_IMPORTER_OR_MANUAL_STAGING" },
    [pscustomobject]@{ Name="V20.26"; Wrapper="run_v20_26_yahoo_runtime_outcome_benchmark_source_adapter.ps1"; StatusFile="outputs\v20\consolidation\V20_26_GATE_DECISION.csv"; StatusField="READY_FOR_V20_27_YAHOO_CACHE_CERTIFICATION_NEXT"; ExpectedStatus="TRUE" },
    [pscustomobject]@{ Name="V20.27"; Wrapper="run_v20_27_yahoo_cache_certification_and_active_input_staging.ps1"; StatusFile="outputs\v20\consolidation\V20_27_GATE_DECISION.csv"; StatusField="READY_FOR_V20_28_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_RETRY_NEXT"; ExpectedStatus="TRUE" },
    [pscustomobject]@{ Name="V20.28"; Wrapper="run_v20_28_outcome_benchmark_value_attachment_retry_from_certified_yahoo_inputs.ps1"; StatusFile="outputs\v20\consolidation\V20_28_GATE_DECISION.csv"; StatusField="READY_FOR_V20_29_FIRST_LIMITED_BACKTEST_READINESS_GATE_NEXT"; ExpectedStatus="TRUE" },
    [pscustomobject]@{ Name="V20.29"; Wrapper="run_v20_29_first_limited_backtest_readiness_gate.ps1"; StatusFile="outputs\v20\consolidation\V20_29_GATE_DECISION.csv"; StatusField="READY_FOR_V20_30_FIRST_LIMITED_BACKTEST_EXECUTION_NEXT"; ExpectedStatus="TRUE" },
    [pscustomobject]@{ Name="V20.30"; Wrapper="run_v20_30_first_limited_backtest_execution.ps1"; StatusFile="outputs\v20\consolidation\V20_30_GATE_DECISION.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_30_FIRST_LIMITED_BACKTEST_EXECUTION" },
    [pscustomobject]@{ Name="V20.31"; Wrapper="run_v20_31_base_price_attachment_for_first_limited_backtest.ps1"; StatusFile="outputs\v20\consolidation\V20_31_GATE_DECISION.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_31_BASE_PRICE_ATTACHMENT_FOR_FIRST_LIMITED_BACKTEST" },
    [pscustomobject]@{ Name="V20.32"; Wrapper="run_v20_32_first_limited_backtest_execution_retry_with_base_prices.ps1"; StatusFile="outputs\v20\consolidation\V20_32_GATE_DECISION.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_32_FIRST_LIMITED_BACKTEST_EXECUTION_RETRY_WITH_BASE_PRICES" },
    [pscustomobject]@{ Name="V20.33"; Wrapper="run_v20_33_first_limited_backtest_result_review_and_sanity_check.ps1"; StatusFile="outputs\v20\consolidation\V20_33_GATE_DECISION.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_33_FIRST_LIMITED_BACKTEST_RESULT_REVIEW_AND_SANITY_CHECK" },
    [pscustomobject]@{ Name="V20.34"; Wrapper="run_v20_34_extreme_return_warning_triage_and_random_backtest_preflight.ps1"; StatusFile="outputs\v20\consolidation\V20_34_RANDOM_ASOF_TOP20_PREFLIGHT_DECISION.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_34_EXTREME_RETURN_WARNING_TRIAGE_AND_RANDOM_BACKTEST_PREFLIGHT" },
    [pscustomobject]@{ Name="V20.35"; Wrapper="run_v20_35_random_asof_top20_technical_recompute_backtest.ps1"; StatusFile="outputs\v20\consolidation\V20_35_NEXT_STEP_DECISION_SUMMARY.csv"; StatusField="STATUS"; ExpectedStatus="" },
    [pscustomobject]@{ Name="V20.35-R1"; Wrapper="run_v20_35_r1_historical_yahoo_cache_expansion_for_random_asof_backtest.ps1"; StatusFile="outputs\v20\consolidation\V20_35_R1_NEXT_STEP_DECISION_SUMMARY.csv"; StatusField="READY_FOR_V20_35_RETRY_RANDOM_ASOF_TOP20_TECHNICAL_RECOMPUTE_BACKTEST"; ExpectedStatus="TRUE" },
    [pscustomobject]@{ Name="V20.35-R2"; Wrapper="run_v20_35_r2_random_asof_top20_technical_recompute_backtest_retry_from_historical_cache.ps1"; StatusFile="outputs\v20\consolidation\V20_35_R2_NEXT_STEP_DECISION_SUMMARY.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_35_R2_RANDOM_ASOF_TOP20_TECHNICAL_RECOMPUTE_BACKTEST_RETRY_FROM_HISTORICAL_CACHE" },
    [pscustomobject]@{ Name="V20.36"; Wrapper="run_v20_36_entry_strategy_matrix_design.ps1"; StatusFile="outputs\v20\consolidation\V20_36_NEXT_STEP_DECISION_SUMMARY.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_36_ENTRY_STRATEGY_MATRIX_DESIGN" },
    [pscustomobject]@{ Name="V20.37"; Wrapper="run_v20_37_entry_strategy_backtest_execution.ps1"; StatusFile="outputs\v20\consolidation\V20_37_NEXT_STEP_DECISION_SUMMARY.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_37_ENTRY_STRATEGY_BACKTEST_EXECUTION" },
    [pscustomobject]@{ Name="V20.38"; Wrapper="run_v20_38_factor_effectiveness_ablation_audit.ps1"; StatusFile="outputs\v20\consolidation\V20_38_NEXT_STEP_DECISION_SUMMARY.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_38_FACTOR_EFFECTIVENESS_ABLATION_AUDIT" },
    [pscustomobject]@{ Name="V20.39"; Wrapper="run_v20_39_shadow_dynamic_weighting_design.ps1"; StatusFile="outputs\v20\consolidation\V20_39_NEXT_STEP_DECISION_SUMMARY.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_39_SHADOW_DYNAMIC_WEIGHTING_DESIGN" },
    [pscustomobject]@{ Name="V20.39-R1"; Wrapper="run_v20_39_r1_shadow_weighted_recompute_backtest.ps1"; StatusFile="outputs\v20\consolidation\V20_39_R1_NEXT_STEP_DECISION_SUMMARY.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_39_R1_SHADOW_WEIGHTED_RECOMPUTE_BACKTEST" },
    [pscustomobject]@{ Name="V20.39-R2"; Wrapper="run_v20_39_r2_shadow_weighted_entry_strategy_backtest.ps1"; StatusFile="outputs\v20\consolidation\V20_39_R2_NEXT_STEP_DECISION_SUMMARY.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_39_R2_SHADOW_WEIGHTED_ENTRY_STRATEGY_BACKTEST" },
    [pscustomobject]@{ Name="V20.40"; Wrapper="run_v20_40_portfolio_level_exploratory_backtest.ps1"; StatusFile="outputs\v20\consolidation\V20_40_NEXT_STEP_DECISION_SUMMARY.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_40_PORTFOLIO_LEVEL_EXPLORATORY_BACKTEST" },
    [pscustomobject]@{ Name="V20.41"; Wrapper="run_v20_41_research_factor_pit_expansion_plan.ps1"; StatusFile="outputs\v20\consolidation\V20_41_NEXT_STEP_DECISION_SUMMARY.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_41_RESEARCH_FACTOR_PIT_EXPANSION_PLAN" },
    [pscustomobject]@{ Name="V20.42"; Wrapper="run_v20_42_daily_operator_research_report_design.ps1"; StatusFile="outputs\v20\consolidation\V20_42_DAILY_OPERATOR_REPORT_NEXT_STEP_DECISION.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_42_DAILY_OPERATOR_RESEARCH_REPORT_DESIGN" },
    [pscustomobject]@{ Name="V20.43"; Wrapper="run_v20_43_daily_operator_report_dry_run.ps1"; StatusFile="outputs\v20\consolidation\V20_43_DAILY_OPERATOR_REPORT_NEXT_STEP_DECISION.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_43_DAILY_OPERATOR_REPORT_DRY_RUN" },
    [pscustomobject]@{ Name="V20.44"; Wrapper="run_v20_44_daily_operator_report_acceptance_gate_or_current_run.ps1"; StatusFile="outputs\v20\consolidation\V20_44_CURRENT_RUN_READINESS_DECISION.csv"; StatusField="decision"; ExpectedStatus="PASS_DAILY_OPERATOR_REPORT_ACCEPTED_FOR_CURRENT_RESEARCH_RUN" },
    [pscustomobject]@{ Name="V20.45"; Wrapper="run_v20_45_current_operator_report_research_only_run.ps1"; StatusFile="outputs\v20\consolidation\V20_45_CURRENT_OPERATOR_NEXT_STEP_DECISION.csv"; StatusField="decision"; ExpectedStatus="PASS_RESEARCH_ONLY_CURRENT_OPERATOR_REPORT_CREATED" },
    [pscustomobject]@{ Name="V20.52"; Wrapper="run_v20_52_official_recommendation_policy_contract_gate.ps1"; StatusFile="outputs\v20\consolidation\V20_52_NEXT_STEP_DECISION.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_52_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_GATE" },
    [pscustomobject]@{ Name="V20.53"; Wrapper="run_v20_53_official_recommendation_schema_dry_run_gate.ps1"; StatusFile="outputs\v20\consolidation\V20_53_NEXT_STEP_DECISION.csv"; StatusField="STATUS"; ExpectedStatus="PASS_V20_53_OFFICIAL_RECOMMENDATION_SCHEMA_DRY_RUN_GATE" },
    [pscustomobject]@{ Name="V20.55"; Wrapper="run_v20_55_daily_one_click_research_runner.ps1"; StatusFile="outputs\v20\consolidation\V20_55_DAILY_ONE_CLICK_RUN_SUMMARY.csv"; StatusField="overall_status"; ExpectedStatus="" }
)

$modifiedPython = @(
    "scripts\v18\v18_13B_ranked_candidate_read_center.py",
    "scripts\v16\repair_v16_second_stage_universe.py",
    "scripts\v18\repair_v18_current_raw105_factor_pack.py",
    "scripts\v18\repair_v18_current_technical_timing.py",
    "scripts\v18\repair_v18_current_ranked_candidates_alias.py",
    "scripts\v18\repair_v18_manual_universe_additions.py",
    "scripts\v18\repair_v18_current_full_ranked_candidates.py",
    "scripts\v18\v18_14A_full_daily_mode_validation.py",
    "scripts\v18\v18_14B_current_daily_command_center.py",
    "scripts\v18\v18_16A_universe_rolling_state_builder.py",
    "scripts\v18\v18_35D_full_universe_factor_technical_recompute.py",
    "scripts\v20\v20_1_current_runtime_and_report_structure_cleanup.py",
    "scripts\v20\v20_2_factor_universe_and_strategy_research_map.py",
    "scripts\v20\v20_3_readable_research_report_framework.py",
    "scripts\v20\v20_4_architecture_clarification_seal_before_data_execution.py",
    "scripts\v20\v20_5_source_registry_activation.py",
    "scripts\v20\v20_6_hash_run_id_version_binding.py",
    "scripts\v20\v20_7_stale_leakage_pit_gate.py",
    "scripts\v20\v20_7r_normalized_data_blocker_resolution_plan.py",
    "scripts\v20\v20_7s_active_market_data_source_certification_and_entry_gate.py",
    "scripts\v20\v20_7t_active_market_data_input_staging_and_registration.py",
    "scripts\v20\v20_7u_active_market_input_intake_and_lineage_binding.py",
    "scripts\v20\v20_7v_active_market_source_staging_from_accepted_v18_result.py",
    "scripts\v20\v20_7w_active_market_source_certification_retry_from_v20_7v_staging.py",
    "scripts\v20\v20_7x_active_market_input_lineage_binding_retry_from_certified_v20_7w_source.py",
    "scripts\v20\v20_8_normalized_research_dataset_construction.py",
    "scripts\v20\v20_9_factor_research_dataset_preparation.py",
    "scripts\v20\v20_10_factor_source_attachment_or_availability_audit.py",
    "scripts\v20\v20_11_factor_source_attachment_plan_or_first_attachable_factor_layer.py",
    "scripts\v20\v20_12_factor_input_layer_review_or_factor_evidence_gate.py",
    "scripts\v20\v20_13_first_limited_factor_evidence_layer.py",
    "scripts\v20\v20_14_factor_evidence_review_or_factor_score_gate.py",
    "scripts\v20\v20_15_first_limited_factor_score_layer.py",
    "scripts\v20\v20_16_factor_score_review_or_backtest_readiness_gate.py",
    "scripts\v20\v20_17_backtest_input_outcome_and_benchmark_preparation.py",
    "scripts\v20\v20_18_outcome_benchmark_source_attachment_or_backtest_readiness_review.py",
    "scripts\v20\v20_19_outcome_benchmark_value_attachment_or_blocker_resolution.py",
    "scripts\v20\v20_20_outcome_benchmark_source_certification_or_blocker_resolution.py",
    "scripts\v20\v20_21_outcome_benchmark_input_staging_and_registration.py",
    "scripts\v20\v20_22_outcome_benchmark_input_certification_retry.py",
    "scripts\v20\v20_23_outcome_benchmark_input_source_creation_or_staging_from_allowed_local_data.py",
    "scripts\v20\v20_24_local_outcome_benchmark_data_requirement_and_acquisition_plan.py",
    "scripts\v20\v20_25_local_outcome_benchmark_importer_or_manual_staging.py",
    "scripts\v20\v20_26_yahoo_runtime_outcome_benchmark_source_adapter.py",
    "scripts\v20\v20_27_yahoo_cache_certification_and_active_input_staging.py",
    "scripts\v20\v20_28_outcome_benchmark_value_attachment_retry_from_certified_yahoo_inputs.py",
    "scripts\v20\v20_29_first_limited_backtest_readiness_gate.py",
    "scripts\v20\v20_30_first_limited_backtest_execution.py",
    "scripts\v20\v20_31_base_price_attachment_for_first_limited_backtest.py",
    "scripts\v20\v20_32_first_limited_backtest_execution_retry_with_base_prices.py",
    "scripts\v20\v20_33_first_limited_backtest_result_review_and_sanity_check.py",
    "scripts\v20\v20_34_extreme_return_warning_triage_and_random_backtest_preflight.py",
    "scripts\v20\v20_35_random_asof_top20_technical_recompute_backtest.py",
    "scripts\v20\v20_35_r1_historical_yahoo_cache_expansion_for_random_asof_backtest.py",
    "scripts\v20\v20_35_r2_random_asof_top20_technical_recompute_backtest_retry_from_historical_cache.py",
    "scripts\v20\v20_36_entry_strategy_matrix_design.py",
    "scripts\v20\v20_37_entry_strategy_backtest_execution.py",
    "scripts\v20\v20_38_factor_effectiveness_ablation_audit.py",
    "scripts\v20\v20_39_shadow_dynamic_weighting_design.py",
    "scripts\v20\v20_39_r1_shadow_weighted_recompute_backtest.py",
    "scripts\v20\v20_39_r2_shadow_weighted_entry_strategy_backtest.py",
    "scripts\v20\v20_40_portfolio_level_exploratory_backtest.py",
    "scripts\v20\v20_41_research_factor_pit_expansion_plan.py",
    "scripts\v20\v20_42_daily_operator_research_report_design.py",
    "scripts\v20\v20_43_daily_operator_report_dry_run.py",
    "scripts\v20\v20_44_daily_operator_report_acceptance_gate_or_current_run.py",
    "scripts\v20\v20_45_current_operator_report_research_only_run.py",
    "scripts\v20\v20_46_current_market_refresh_readiness_gate.py",
    "scripts\v20\v20_47_controlled_current_market_refresh_and_cache_certification.py",
    "scripts\v20\v20_post_refresh_recompute_handoff.py",
    "scripts\v20\v20_48_refreshed_current_operator_research_report.py",
    "scripts\v20\v20_49_operator_review_acceptance_gate.py",
    "scripts\v20\v20_50_research_only_decision_packet.py",
    "scripts\v20\v20_51_official_recommendation_readiness_gate.py",
    "scripts\v20\v20_52_official_recommendation_policy_contract_gate.py",
    "scripts\v20\v20_53_official_recommendation_schema_dry_run_gate.py",
    "scripts\v20\v20_54_user_readable_current_decision_report.py",
    "scripts\v20\v20_55_daily_one_click_research_runner.py",
    "scripts\v20\test_v20_current_chain_bootstrap_repair.py"
)

Push-Location $RepoRoot
try {
    foreach ($path in $modifiedPython) {
        if (Test-Path $path) {
            & $Python -m py_compile $path
            if ($LASTEXITCODE -ne 0) {
                throw "py_compile failed for $path"
            }
        }
    }

    foreach ($stage in $stages) {
        $wrapper = Resolve-StageWrapper $stage
        if (Test-Path $wrapper) {
            [scriptblock]::Create((Get-Content -Raw -Path $wrapper)) | Out-Null
        }
    }

    $statusRows = [System.Collections.Generic.List[object]]::new()
    $finalStatus = "PASS"
    $firstFailedStage = ""
    $blockerReason = ""
    $forwardLaneStatus = "PASS"
    $forwardFirstFailedStage = ""
    $forwardBlockerReason = ""
    $forwardPending = $false
    $skipAfterForwardPending = @(
        "V20.28", "V20.29", "V20.30", "V20.31", "V20.32", "V20.33", "V20.34",
        "V20.35", "V20.35-R1", "V20.35-R2", "V20.36", "V20.37", "V20.38",
        "V20.39", "V20.39-R1", "V20.39-R2", "V20.40", "V20.41", "V20.42",
        "V20.43", "V20.44", "V20.45", "V20.52", "V20.53"
    )

    foreach ($stage in $stages) {
        if ($forwardPending -and ($skipAfterForwardPending -contains $stage.Name)) {
            $statusRows.Add([pscustomobject]@{
                stage = $stage.Name
                wrapper = $stage.Wrapper
                exit_code = 0
                status = "SKIPPED_FORWARD_OUTCOME_VALIDATION_PENDING"
                passed = "TRUE"
                blocker_reason = "Skipped in current daily research lane because V20.27 is pending PIT-safe forward target dates."
            })
            continue
        }
        $result = Invoke-CheckedStage $stage
        $statusRows.Add($result)
        Write-DependencyMatrix
        if ($result.passed -ne "TRUE") {
            $matrixBlocker = Get-BlockerFromMatrix
            $candidateBlocker = if ($matrixBlocker) { $matrixBlocker } else { $result.blocker_reason }
            if ($result.stage -eq "V20.27") {
                $gap = Get-ForwardOutcomeGapSummary
                if ($gap.pending_forward_target_dates -eq "TRUE") {
                    $forwardPending = $true
                    $forwardLaneStatus = "PENDING_FORWARD_TARGET_DATES"
                    $forwardFirstFailedStage = "V20.27"
                    $forwardBlockerReason = $candidateBlocker
                    continue
                }
            }
            $finalStatus = "BLOCKED"
            $firstFailedStage = $result.stage
            $blockerReason = $candidateBlocker
            break
        }
    }

    if (-not $firstFailedStage) {
        Write-DependencyMatrix
        $matrixBlocker = Get-BlockerFromMatrix
        if ($matrixBlocker -and -not $forwardPending) {
            $finalStatus = "BLOCKED"
            $firstFailedStage = "dependency_matrix"
            $blockerReason = $matrixBlocker
        }
    }

    $v55 = Read-FirstCsvRow (Join-Path $Consolidation "V20_55_DAILY_ONE_CLICK_RUN_SUMMARY.csv")
    $v55Status = Get-FieldValue $v55 "overall_status"
    $v55Pass = $v55Status -eq "PASS_V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER"
    $v55Warn = $v55Status -eq "WARN_V20_55_RESEARCH_ONLY_READY_PROMOTION_BLOCKED"
    if ($finalStatus -eq "PASS" -and -not ($v55Pass -or $v55Warn)) {
        $finalStatus = "BLOCKED"
        $firstFailedStage = "V20.55"
        $blockerReason = "V20.55 did not report PASS; actual=$v55Status"
    }
    $currentLaneStatus = if ($finalStatus -eq "BLOCKED") { "BLOCKED" } elseif ($v55Warn) { "WARN" } else { "PASS" }
    $currentFirstFailedStage = if ($currentLaneStatus -eq "BLOCKED") { $firstFailedStage } else { "" }
    $currentBlockerReason = if ($currentLaneStatus -eq "BLOCKED") { $blockerReason } else { "" }
    if ($forwardPending -and $currentLaneStatus -in @("PASS", "WARN")) {
        $finalStatus = "PARTIAL_PASS_CURRENT_DAILY_RESEARCH_READY_FORWARD_OUTCOME_PENDING"
        $firstFailedStage = $forwardFirstFailedStage
        $blockerReason = $forwardBlockerReason
    }
    $forwardGap = Get-ForwardOutcomeGapSummary
    Write-LaneStatusFiles $currentLaneStatus $currentFirstFailedStage $currentBlockerReason $forwardLaneStatus $forwardFirstFailedStage $forwardBlockerReason $forwardGap
    Write-DailyConclusion $finalStatus $firstFailedStage $blockerReason $v55Status
    Add-Content -Path $ConclusionPath -Value @"

## Chain Lane Status

current_daily_research_lane_status: $currentLaneStatus
current_daily_research_first_failed_stage: $currentFirstFailedStage
forward_outcome_validation_lane_status: $forwardLaneStatus
forward_outcome_first_failed_stage: $forwardFirstFailedStage
pending_forward_target_dates: $($forwardGap.pending_forward_target_dates)
latest_available_cache_date: $($forwardGap.latest_available_cache_date)
first_required_target_date: $($forwardGap.first_required_target_date)
latest_required_target_date: $($forwardGap.latest_required_target_date)
official_promotion_allowed: FALSE
official_recommendation_created: FALSE
weight_mutated: FALSE
trade_action_created: FALSE
"@
    $nextAction = if ($finalStatus -eq "PASS") { "Run formal V20.55 test and operator review of research-only report." } elseif ($finalStatus -eq "PARTIAL_PASS_CURRENT_DAILY_RESEARCH_READY_FORWARD_OUTCOME_PENDING") { "Current daily research lane is ready; wait for PIT-safe forward target dates or import authoritative outcome/benchmark rows before promotion." } else { "Resolve $blockerReason" }

    $statusRows.Add([pscustomobject]@{
        stage = "FINAL"
        wrapper = ""
        exit_code = 0
        status = $finalStatus
        passed = if ($finalStatus -in @("PASS", "PARTIAL_PASS_CURRENT_DAILY_RESEARCH_READY_FORWARD_OUTCOME_PENDING")) { "TRUE" } else { "FALSE" }
        blocker_reason = $blockerReason
    })
    $statusRows | Export-Csv -Path $StatusPath -NoTypeInformation

    $summary = @"
# V20 Current Chain Bootstrap Repair Summary

final_status: $finalStatus
first_failed_stage: $firstFailedStage
blocker_reason: $blockerReason
next_recommended_action: $nextAction
v20_55_pass_achieved: $(if ($v55Pass) { "TRUE" } else { "FALSE" })
current_daily_research_lane_status: $currentLaneStatus
forward_outcome_validation_lane_status: $forwardLaneStatus
forward_outcome_first_failed_stage: $forwardFirstFailedStage
pending_forward_target_dates: $($forwardGap.pending_forward_target_dates)
latest_available_cache_date: $($forwardGap.latest_available_cache_date)
first_required_target_date: $($forwardGap.first_required_target_date)
latest_required_target_date: $($forwardGap.latest_required_target_date)

## Outputs

- dependency_matrix: outputs/v20/repair/V20_CURRENT_CHAIN_DEPENDENCY_MATRIX.csv
- repair_status: outputs/v20/repair/V20_CURRENT_CHAIN_BOOTSTRAP_REPAIR_STATUS.csv
- lane_status: outputs/v20/repair/V20_CURRENT_CHAIN_LANE_STATUS.csv
- current_daily_research_lane_status: outputs/v20/repair/V20_CURRENT_DAILY_RESEARCH_LANE_STATUS.csv
- forward_outcome_validation_lane_status: outputs/v20/repair/V20_FORWARD_OUTCOME_VALIDATION_LANE_STATUS.csv
- daily_conclusion: outputs/v20/read_center/V20_CURRENT_DAILY_CONCLUSION.md

## Safety Boundary

- research_only: TRUE
- official_recommendation_created: FALSE
- buy_sell_hold_instructions_created: FALSE
- trading_signal_created: FALSE
- broker_order_execution_connected: FALSE
- official_ranking_mutated: FALSE
- official_factor_weights_mutated: FALSE
- dynamic_weights_mutated: FALSE
- v21_outputs_created: FALSE
- v19_21_outputs_created: FALSE
"@
    Set-Content -Path $SummaryPath -Value $summary -Encoding UTF8

    Write-Host "final_status=$finalStatus"
    Write-Host "first_failed_stage=$firstFailedStage"
    Write-Host "blocker_reason=$blockerReason"
    Write-Host "next_recommended_action=$nextAction"
    Write-Host "v20_55_pass_achieved=$(if ($v55Pass) { "TRUE" } else { "FALSE" })"

    exit 0
}
finally {
    Pop-Location
}
