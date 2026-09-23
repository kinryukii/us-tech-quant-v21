param(
    [string]$Python = "python",
    [switch]$SkipStageExecution
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$RepairDir = Join-Path $RepoRoot "outputs\v20\repair"
$EvidenceDir = Join-Path $RepoRoot "outputs\v20\evidence"
$ReadCenter = Join-Path $RepoRoot "outputs\v20\read_center"
$Consolidation = Join-Path $RepoRoot "outputs\v20\consolidation"

$StatusCsv = Join-Path $EvidenceDir "V20_DAILY_RESEARCH_OBSERVATION_OPERATOR_STATUS.csv"
$StatusSummary = Join-Path $EvidenceDir "V20_DAILY_RESEARCH_OBSERVATION_OPERATOR_SUMMARY.md"
$StatusCsvAlias = Join-Path $EvidenceDir "V20_CURRENT_DAILY_RESEARCH_OBSERVATION_OPERATOR_STATUS.csv"
$StatusSummaryAlias = Join-Path $EvidenceDir "V20_CURRENT_DAILY_RESEARCH_OBSERVATION_OPERATOR_SUMMARY.md"
$LedgerPath = Join-Path $EvidenceDir "V20_DAILY_RESEARCH_OBSERVATION_LEDGER.csv"
$LedgerAliasPath = Join-Path $EvidenceDir "V20_CURRENT_DAILY_RESEARCH_OBSERVATION_LEDGER.csv"
$LedgerSummaryPath = Join-Path $EvidenceDir "V20_DAILY_RESEARCH_OBSERVATION_LEDGER_SUMMARY.md"

$ConclusionPath = Join-Path $ReadCenter "V20_CURRENT_DAILY_CONCLUSION.md"
$ChainLanePath = Join-Path $RepairDir "V20_CURRENT_CHAIN_LANE_STATUS.csv"
$DailyLanePath = Join-Path $RepairDir "V20_CURRENT_DAILY_RESEARCH_LANE_STATUS.csv"
$ForwardLanePath = Join-Path $RepairDir "V20_FORWARD_OUTCOME_VALIDATION_LANE_STATUS.csv"
$V55SummaryPath = Join-Path $Consolidation "V20_55_DAILY_ONE_CLICK_RUN_SUMMARY.csv"
$V97SummaryPath = Join-Path $EvidenceDir "V20_97_DAILY_RUNNER_OBSERVATION_BRIDGE_REPAIR_SUMMARY.md"
$V96SummaryPath = Join-Path $EvidenceDir "V20_96_MULTI_RUN_OBSERVATION_ACCUMULATION_SUMMARY.md"
$V97BridgePath = Join-Path $EvidenceDir "V20_CURRENT_DAILY_RUNNER_OBSERVATION_BRIDGE.csv"

$LedgerFields = @(
    "run_id",
    "observation_timestamp",
    "observation_date",
    "v20_55_status",
    "daily_conclusion_mode",
    "current_daily_research_lane_status",
    "forward_outcome_validation_lane_status",
    "observation_class",
    "research_observation_valid",
    "official_promotion_eligible",
    "promotion_blocker_present",
    "promotion_blocked_reason",
    "v20_27_forward_pending",
    "research_only",
    "promotion_allowed",
    "official_recommendation_created",
    "official_weight_mutated",
    "weight_mutated",
    "trade_action_created",
    "source_artifact_path",
    "provenance_status",
    "ledger_write_timestamp"
)

New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null

function Read-FirstCsvRow([string]$Path) {
    if (-not (Test-Path $Path)) {
        return $null
    }
    $rows = @(Import-Csv -Path $Path)
    if ($rows.Count -eq 0) {
        return $null
    }
    return $rows[0]
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

function Read-SummaryValue([string]$Path, [string]$Key) {
    if (-not (Test-Path $Path)) {
        return ""
    }
    foreach ($line in Get-Content -Path $Path) {
        if ($line -match "^\s*-?\s*$([regex]::Escape($Key))\s*:\s*(.*)$") {
            return $Matches[1].Trim()
        }
    }
    return ""
}

function Invoke-Stage([string]$StagePath) {
    Write-Host "RUNNING_STAGE=$StagePath"
    $output = & powershell -NoProfile -ExecutionPolicy Bypass -File $StagePath -Python $Python 2>&1
    $exitCode = $LASTEXITCODE
    $output | ForEach-Object { Write-Host $_ }
    if ($exitCode -ne 0) {
        throw "stage failed: $StagePath exit_code=$exitCode"
    }
}

function To-BoolText([bool]$Value) {
    if ($Value) { return "TRUE" }
    return "FALSE"
}

function Get-NowUtcText {
    return [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
}

function New-LedgerRowFromBridgeRow([object]$BridgeRow) {
    $runId = Get-FieldValue $BridgeRow "run_id"
    if (-not $runId) {
        $runId = Get-FieldValue $BridgeRow "observation_run_id"
    }
    $timestamp = Get-FieldValue $BridgeRow "observation_timestamp"
    if (-not $timestamp) {
        $timestamp = Get-FieldValue $BridgeRow "source_timestamp_utc"
    }
    $date = Get-FieldValue $BridgeRow "observation_date"
    if (-not $date -and $timestamp.Length -ge 10) {
        $date = $timestamp.Substring(0, 10)
    }
    return [ordered]@{
        run_id = $runId
        observation_timestamp = $timestamp
        observation_date = $date
        v20_55_status = Get-FieldValue $BridgeRow "v20_55_status"
        daily_conclusion_mode = Get-FieldValue $BridgeRow "daily_conclusion_mode"
        current_daily_research_lane_status = Get-FieldValue $BridgeRow "current_daily_research_lane_status"
        forward_outcome_validation_lane_status = Get-FieldValue $BridgeRow "forward_outcome_validation_lane_status"
        observation_class = Get-FieldValue $BridgeRow "observation_class"
        research_observation_valid = Get-FieldValue $BridgeRow "research_observation_valid"
        official_promotion_eligible = Get-FieldValue $BridgeRow "official_promotion_eligible"
        promotion_blocker_present = Get-FieldValue $BridgeRow "promotion_blocker_present"
        promotion_blocked_reason = Get-FieldValue $BridgeRow "promotion_blocked_reason"
        v20_27_forward_pending = Get-FieldValue $BridgeRow "v20_27_forward_pending"
        research_only = Get-FieldValue $BridgeRow "research_only"
        promotion_allowed = Get-FieldValue $BridgeRow "promotion_allowed"
        official_recommendation_created = Get-FieldValue $BridgeRow "official_recommendation_created"
        official_weight_mutated = Get-FieldValue $BridgeRow "official_weight_mutated"
        weight_mutated = Get-FieldValue $BridgeRow "weight_mutated"
        trade_action_created = Get-FieldValue $BridgeRow "trade_action_created"
        source_artifact_path = Get-FieldValue $BridgeRow "source_artifact_path"
        provenance_status = Get-FieldValue $BridgeRow "provenance_status"
        ledger_write_timestamp = Get-NowUtcText
    }
}

function ConvertTo-LedgerObject([object]$Values) {
    $ordered = [ordered]@{}
    foreach ($field in $LedgerFields) {
        $ordered[$field] = if ($Values.Contains($field)) { [string]$Values[$field] } else { "" }
    }
    return [pscustomobject]$ordered
}

function Get-RecoveryDiagnostics {
    $knownMissing = "V20_55_20260612T170722Z"
    $sourceFiles = @()
    $recovered = 0
    $unrecoverable = @()
    $outputMatches = @(
        Get-ChildItem -Path (Join-Path $RepoRoot "outputs\v20") -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -notmatch "DAILY_RESEARCH_OBSERVATION_(LEDGER|OPERATOR)" } |
            Select-String -Pattern $knownMissing -SimpleMatch -ErrorAction SilentlyContinue
    )
    foreach ($match in $outputMatches) {
        if ($match.Path) {
            $sourceFiles += $match.Path.Replace($RepoRoot.Path, "").TrimStart("\").Replace("\", "/")
        }
    }
    $gitMatches = @()
    try {
        $gitMatches = @(git grep -n $knownMissing $(git rev-list --all) -- outputs/v20 2>$null | Where-Object { $_ -and ($_ -notmatch "DAILY_RESEARCH_OBSERVATION_(LEDGER|OPERATOR)") })
    }
    catch {
        $gitMatches = @()
    }
    foreach ($match in $gitMatches) {
        if ($match) {
            $sourceFiles += "git:$match"
        }
    }
    if ($sourceFiles.Count -gt 0) {
        $recovered = 0
        $unrecoverable += "$knownMissing:FOUND_REFERENCE_ONLY_NOT_IMPORTED"
    }
    else {
        $unrecoverable += $knownMissing
    }
    return @{
        recovered_run_count = "$recovered"
        unrecoverable_known_run_ids = ($unrecoverable -join "|")
        recovery_source_files = if ($sourceFiles.Count -gt 0) { (($sourceFiles | Select-Object -Unique) -join "|") } else { "NONE" }
        recovery_status = if ($sourceFiles.Count -gt 0) { "REFERENCE_FOUND_NOT_IMPORTED_WITHOUT_RECOVERABLE_ARTIFACT" } else { "NOT_RECOVERABLE" }
    }
}

function Write-LedgerSummary([array]$Rows, [hashtable]$Recovery) {
    $validRows = @($Rows | Where-Object { $_.research_observation_valid -eq "TRUE" })
    $officialRows = @($Rows | Where-Object { $_.official_promotion_eligible -eq "TRUE" })
    $lines = @(
        "# V20 Daily Research Observation Ledger",
        "",
        "## Counts",
        "- ledger_row_count: $($Rows.Count)",
        "- research_observation_count: $($validRows.Count)",
        "- official_promotion_eligible_count: $($officialRows.Count)",
        "",
        "## Recovery Diagnostics",
        "- recovered_run_count: $($Recovery.recovered_run_count)",
        "- unrecoverable_known_run_ids: $($Recovery.unrecoverable_known_run_ids)",
        "- recovery_source_files: $($Recovery.recovery_source_files)",
        "- recovery_status: $($Recovery.recovery_status)",
        "",
        "## Safety",
        "- research_only: TRUE",
        "- promotion_allowed: FALSE",
        "- official_recommendation_created: FALSE",
        "- official_weight_mutated: FALSE",
        "- weight_mutated: FALSE",
        "- trade_action_created: FALSE",
        ""
    )
    Set-Content -Path $LedgerSummaryPath -Value $lines -Encoding UTF8
}

function Update-DailyResearchObservationLedger {
    $existingRows = @()
    if (Test-Path $LedgerPath) {
        $existingRows = @(Import-Csv -Path $LedgerPath)
    }
    $bridgeRows = @()
    if (Test-Path $V97BridgePath) {
        $bridgeRows = @(Import-Csv -Path $V97BridgePath)
    }
    $byRunId = [ordered]@{}
    foreach ($row in $existingRows) {
        $runId = Get-FieldValue $row "run_id"
        if ($runId) {
            $values = @{}
            foreach ($field in $LedgerFields) {
                $values[$field] = Get-FieldValue $row $field
            }
            $byRunId[$runId] = $values
        }
    }
    foreach ($row in $bridgeRows) {
        if ((Get-FieldValue $row "research_observation_valid") -ne "TRUE") {
            continue
        }
        $values = New-LedgerRowFromBridgeRow $row
        $runId = $values["run_id"]
        if (-not $runId) {
            continue
        }
        $byRunId[$runId] = $values
    }
    $rows = @()
    foreach ($key in $byRunId.Keys) {
        $rows += ConvertTo-LedgerObject $byRunId[$key]
    }
    $rows = @($rows | Sort-Object observation_timestamp, run_id)
    if ($rows.Count -gt 0) {
        $rows | Export-Csv -Path $LedgerPath -NoTypeInformation
    }
    else {
        $empty = New-Object PSObject
        foreach ($field in $LedgerFields) {
            $empty | Add-Member -NotePropertyName $field -NotePropertyValue ""
        }
        @($empty) | Export-Csv -Path $LedgerPath -NoTypeInformation
        (Get-Content $LedgerPath | Select-Object -First 1) | Set-Content -Path $LedgerPath -Encoding UTF8
    }
    Copy-Item -Path $LedgerPath -Destination $LedgerAliasPath -Force
    $recovery = Get-RecoveryDiagnostics
    Write-LedgerSummary $rows $recovery
    Write-Host "LEDGER_ROW_COUNT=$($rows.Count)"
    Write-Host "LEDGER_RECOVERY_STATUS=$($recovery.recovery_status)"
}

function Write-StatusArtifacts([hashtable]$Status) {
    $row = [pscustomobject]$Status
    $row | Export-Csv -Path $StatusCsv -NoTypeInformation
    Copy-Item -Path $StatusCsv -Destination $StatusCsvAlias -Force

    $lines = @(
        "# V20 Daily Research Observation Operator",
        "",
        "## Status",
        "- final_status: $($Status.final_status)",
        "- current_daily_research_lane_status: $($Status.current_daily_research_lane_status)",
        "- forward_outcome_validation_lane_status: $($Status.forward_outcome_validation_lane_status)",
        "- v20_55_status: $($Status.v20_55_status)",
        "- v20_97_status: $($Status.v20_97_status)",
        "- v20_96_status: $($Status.v20_96_status)",
        "- research_observation_count: $($Status.research_observation_count)",
        "- required_run_count: $($Status.required_run_count)",
        "- official_promotion_eligible_count: $($Status.official_promotion_eligible_count)",
        "- v20_27_forward_pending: $($Status.v20_27_forward_pending)",
        "- official_promotion_allowed: $($Status.official_promotion_allowed)",
        "- next_recommended_action: $($Status.next_recommended_action)",
        "",
        "## Safety",
        "- research_only: TRUE",
        "- official_recommendation_created: $($Status.official_recommendation_created)",
        "- weight_mutated: $($Status.weight_mutated)",
        "- trade_action_created: $($Status.trade_action_created)",
        "- broker_execution_supported: FALSE",
        ""
    )
    Set-Content -Path $StatusSummary -Value $lines -Encoding UTF8
    Copy-Item -Path $StatusSummary -Destination $StatusSummaryAlias -Force
}

Write-Host "STAGE_NAME=V20_DAILY_RESEARCH_OBSERVATION_OPERATOR"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "PROMOTION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RECOMMENDATION_CREATED=FALSE"
Write-Host "WEIGHT_MUTATED=FALSE"
Write-Host "TRADE_ACTION_CREATED=FALSE"
Write-Host "BROKER_EXECUTION_SUPPORTED=FALSE"

Push-Location $RepoRoot
try {
    if (-not $SkipStageExecution) {
        Invoke-Stage (Join-Path $ScriptDir "run_v20_current_chain_bootstrap_repair.ps1")
        Invoke-Stage (Join-Path $ScriptDir "run_v20_55_daily_one_click_research_runner.ps1")
        Invoke-Stage (Join-Path $ScriptDir "run_v20_97_daily_runner_observation_bridge_repair.ps1")
        Update-DailyResearchObservationLedger
        Invoke-Stage (Join-Path $ScriptDir "run_v20_96_multi_run_observation_accumulation_orchestrator.ps1")
    }
    else {
        Update-DailyResearchObservationLedger
    }

    $dailyLane = Read-FirstCsvRow $DailyLanePath
    $forwardLane = Read-FirstCsvRow $ForwardLanePath
    $v55Summary = Read-FirstCsvRow $V55SummaryPath
    $bridgeRows = @()
    if (Test-Path $V97BridgePath) {
        $bridgeRows = @(Import-Csv -Path $V97BridgePath)
    }

    $currentDailyResearchLaneStatus = Get-FieldValue $dailyLane "lane_status"
    $forwardOutcomeValidationLaneStatus = Get-FieldValue $forwardLane "lane_status"
    $v2055Status = Get-FieldValue $v55Summary "overall_status"
    $v2097Status = Read-SummaryValue $V97SummaryPath "final_status"
    $v2096Status = Read-SummaryValue $V96SummaryPath "final_status"
    $researchObservationCount = Read-SummaryValue $V96SummaryPath "research_observation_count"
    if (-not $researchObservationCount) {
        $researchObservationCount = Read-SummaryValue $V96SummaryPath "valid_observation_run_count"
    }
    $requiredRunCount = Read-SummaryValue $V96SummaryPath "required_run_count"
    $officialPromotionEligibleCount = Read-SummaryValue $V96SummaryPath "official_promotion_eligible_count"
    $v2027ForwardPending = Get-FieldValue $forwardLane "pending_forward_target_dates"
    $officialPromotionAllowed = Get-FieldValue $dailyLane "official_promotion_allowed"
    if (-not $officialPromotionAllowed) {
        $officialPromotionAllowed = Get-FieldValue $forwardLane "official_promotion_allowed"
    }

    $officialRecommendationCreated = "FALSE"
    $weightMutated = "FALSE"
    $tradeActionCreated = "FALSE"
    foreach ($row in $bridgeRows) {
        if ((Get-FieldValue $row "official_recommendation_created") -eq "TRUE") {
            $officialRecommendationCreated = "TRUE"
        }
        if (((Get-FieldValue $row "weight_mutated") -eq "TRUE") -or ((Get-FieldValue $row "official_weight_mutated") -eq "TRUE")) {
            $weightMutated = "TRUE"
        }
        if ((Get-FieldValue $row "trade_action_created") -eq "TRUE") {
            $tradeActionCreated = "TRUE"
        }
    }

    $conclusionExists = (Test-Path $ConclusionPath) -and ((Get-Item $ConclusionPath).Length -gt 0)
    $researchCountInt = 0
    $requiredRunCountInt = 5
    [void][int]::TryParse($researchObservationCount, [ref]$researchCountInt)
    [void][int]::TryParse($requiredRunCount, [ref]$requiredRunCountInt)
    $officialEligibleInt = 0
    [void][int]::TryParse($officialPromotionEligibleCount, [ref]$officialEligibleInt)

    $blocked = $false
    $blockerReason = @()
    if (-not $conclusionExists) {
        $blocked = $true
        $blockerReason += "MISSING_DAILY_CONCLUSION_ARTIFACT"
    }
    if ($currentDailyResearchLaneStatus -notin @("PASS", "WARN")) {
        $blocked = $true
        $blockerReason += "CURRENT_DAILY_RESEARCH_LANE_BLOCKED"
    }
    if ($officialPromotionAllowed -eq "TRUE") {
        $blocked = $true
        $blockerReason += "OFFICIAL_PROMOTION_ALLOWED_UNEXPECTED"
    }
    if ($officialRecommendationCreated -eq "TRUE" -or $weightMutated -eq "TRUE" -or $tradeActionCreated -eq "TRUE") {
        $blocked = $true
        $blockerReason += "UNSAFE_OUTPUT_CREATED"
    }

    if ($blocked) {
        $finalStatus = "BLOCKED_V20_DAILY_RESEARCH_OBSERVATION_OPERATOR"
        $nextRecommendedAction = "repair_blocker_before_collecting_daily_observation"
    }
    elseif ($researchCountInt -lt $requiredRunCountInt) {
        $finalStatus = "WARN_V20_DAILY_RESEARCH_OBSERVATION_ACCUMULATION_IN_PROGRESS"
        $nextRecommendedAction = "continue_collecting_daily_research_only_observations_until_required_run_count_is_met"
    }
    else {
        $finalStatus = "PASS_V20_DAILY_RESEARCH_OBSERVATIONS_READY_PROMOTION_BLOCKED"
        $nextRecommendedAction = "rerun_promotion_blocker_decomposition_after_observation_sufficiency_and_keep_promotion_blocked_until_all_gates_pass"
    }

    $status = @{
        final_status = $finalStatus
        current_daily_research_lane_status = $currentDailyResearchLaneStatus
        forward_outcome_validation_lane_status = $forwardOutcomeValidationLaneStatus
        v20_55_status = $v2055Status
        v20_97_status = $v2097Status
        v20_96_status = $v2096Status
        research_observation_count = "$researchCountInt"
        required_run_count = "$requiredRunCountInt"
        official_promotion_eligible_count = "$officialEligibleInt"
        v20_27_forward_pending = $v2027ForwardPending
        official_promotion_allowed = $officialPromotionAllowed
        official_recommendation_created = $officialRecommendationCreated
        weight_mutated = $weightMutated
        trade_action_created = $tradeActionCreated
        daily_conclusion_artifact_exists = (To-BoolText $conclusionExists)
        blocker_reason = ($blockerReason -join "|")
        next_recommended_action = $nextRecommendedAction
    }

    Write-StatusArtifacts $status
    foreach ($key in @(
        "final_status",
        "current_daily_research_lane_status",
        "forward_outcome_validation_lane_status",
        "v20_55_status",
        "v20_97_status",
        "v20_96_status",
        "research_observation_count",
        "required_run_count",
        "official_promotion_eligible_count",
        "v20_27_forward_pending",
        "official_promotion_allowed",
        "next_recommended_action"
    )) {
        Write-Host "$key=$($status[$key])"
    }
    Write-Host $finalStatus
    if ($finalStatus -eq "BLOCKED_V20_DAILY_RESEARCH_OBSERVATION_OPERATOR") {
        exit 1
    }
}
catch {
    $status = @{
        final_status = "BLOCKED_V20_DAILY_RESEARCH_OBSERVATION_OPERATOR"
        current_daily_research_lane_status = ""
        forward_outcome_validation_lane_status = ""
        v20_55_status = ""
        v20_97_status = ""
        v20_96_status = ""
        research_observation_count = "0"
        required_run_count = "5"
        official_promotion_eligible_count = "0"
        v20_27_forward_pending = ""
        official_promotion_allowed = "FALSE"
        official_recommendation_created = "FALSE"
        weight_mutated = "FALSE"
        trade_action_created = "FALSE"
        daily_conclusion_artifact_exists = "FALSE"
        blocker_reason = $_.Exception.Message
        next_recommended_action = "repair_operator_wrapper_blocker"
    }
    Write-StatusArtifacts $status
    Write-Host "final_status=BLOCKED_V20_DAILY_RESEARCH_OBSERVATION_OPERATOR"
    Write-Host "BLOCKER_REASON=$($_.Exception.Message)"
    Write-Host "BLOCKED_V20_DAILY_RESEARCH_OBSERVATION_OPERATOR"
    exit 1
}
finally {
    Pop-Location
}
