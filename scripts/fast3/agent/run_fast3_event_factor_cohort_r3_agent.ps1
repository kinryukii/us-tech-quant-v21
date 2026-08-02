[CmdletBinding()]
param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$DataRoot = "D:\us-tech-quant-data",
    [string]$ExternalResultsRoot = "D:\us-tech-quant-results",
    [string]$CacheRoot = "D:\us-tech-quant-cache",
    [string]$Model = "",
    [switch]$SkipPreflight
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Write-Section([string]$Text) {
    Write-Host ""
    Write-Host ("=" * 78)
    Write-Host (" " + $Text)
    Write-Host ("=" * 78)
}

function Resolve-PriorRun(
    [string]$ExternalPath,
    [string]$LegacyCompatibilityPath,
    [string]$SummaryName,
    [string]$ExpectedDecision
) {
    $root = if (Test-Path -LiteralPath $ExternalPath -PathType Container) {
        $ExternalPath
    } elseif (Test-Path -LiteralPath $LegacyCompatibilityPath -PathType Container) {
        $LegacyCompatibilityPath
    } else {
        $null
    }
    if ($null -eq $root) { throw "Required prior run was not found in approved external storage: $ExternalPath or $LegacyCompatibilityPath" }
    $summaryPath = Join-Path $root $SummaryName
    if (-not (Test-Path -LiteralPath $summaryPath -PathType Leaf)) { throw "Prior summary missing: $summaryPath" }
    $summary = Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$summary.FINAL_DECISION -ne $ExpectedDecision) {
        throw "Prior decision mismatch at $summaryPath. Expected=$ExpectedDecision Actual=$($summary.FINAL_DECISION)"
    }
    return $root
}

$RepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)
$DataRoot = [System.IO.Path]::GetFullPath($DataRoot)
. (Join-Path $PSScriptRoot "fast3_storage_contract_r1.ps1")
$Storage = Resolve-Fast3StorageContract -RepoRoot $RepoRoot -ExternalResultsRoot $ExternalResultsRoot -CacheRoot $CacheRoot

$PromptPath = Join-Path $RepoRoot "docs\fast3\agent\FAST3_EVENT_FACTOR_COHORT_R3_AGENT.md"
$LimitsPath = Join-Path $RepoRoot "config\fast3\agent\FAST3_EVENT_FACTOR_COHORT_R3_LIMITS.json"
foreach ($required in @($PromptPath, $LimitsPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required deployed file is missing: $required" }
}

$R1External = Join-Path $Storage.RuntimeRoot "fast3\agent_runs\event_factor_law_discovery\20260802_184840"
$R1LegacyCompatibility = Join-Path $Storage.LegacyCompatibilityRoot "fast3\event_factor_law_discovery\20260802_184840"
$R1Root = Resolve-PriorRun -ExternalPath $R1External -LegacyCompatibilityPath $R1LegacyCompatibility `
    -SummaryName "fast3_event_factor_summary.json" -ExpectedDecision "STOP_IMPLEMENTATION_INVALID"

$R2External = Join-Path $Storage.RuntimeRoot "fast3\agent_runs\event_factor_law_discovery_r2\20260802_194125"
$R2LegacyCompatibility = Join-Path $Storage.LegacyCompatibilityRoot "fast3\event_factor_law_discovery_r2\20260802_194125"
$R2Root = Resolve-PriorRun -ExternalPath $R2External -LegacyCompatibilityPath $R2LegacyCompatibility `
    -SummaryName "fast3_event_factor_r2_summary.json" -ExpectedDecision "STOP_CONTROL_MATCH_INCOMPLETE_BEFORE_TRAINING"

$R1Required = @(
    "FAST3_FACTOR_DICTIONARY.json",
    "FAST3_ROUND_LEDGER.jsonl",
    "fast3_event_factor_summary.json"
)
$R2Required = @(
    "fast3_event_factor_r2_summary.json",
    "FAST3_CONTROL_MATCH_AUDIT.json",
    "fast3_event_control_pairs.parquet",
    "fast3_event_ledger.parquet"
)
foreach ($name in $R1Required) {
    $p = Join-Path $R1Root $name
    if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { throw "Required R1 evidence missing: $p" }
}
foreach ($name in $R2Required) {
    $p = Join-Path $R2Root $name
    if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { throw "Required R2 evidence missing: $p" }
}

$r2Summary = Get-Content -LiteralPath (Join-Path $R2Root "fast3_event_factor_r2_summary.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if ([int]$r2Summary.CONTROL_MATCHED_EVENTS -ne 477456 -or [int]$r2Summary.CONTROL_UNMATCHED_EVENTS -ne 39740) {
    throw "R2 frozen matched/unmatched counts do not equal 477456/39740."
}
if ([int]$r2Summary.TRAINING_ROUND_COUNT -ne 0 -or [bool]$r2Summary.FACTOR_LAW_OR_MODEL_FIT_PERFORMED) {
    throw "R2 source is not a pre-training stop and cannot be used under the R3 contract."
}

$StateRoot = Join-Path $Storage.CacheRoot "runtime_locks\fast3\agent\event_factor_cohort_r3"
$RuntimeResultsBase = Join-Path $Storage.RuntimeRoot "fast3\agent_runs\event_factor_cohort_r3"
$FrozenResultsBase = Join-Path $Storage.FrozenRoot "fast3\agent_runs\event_factor_cohort_r3"
New-Item -ItemType Directory -Force -Path $StateRoot, $RuntimeResultsBase, $FrozenResultsBase | Out-Null

$LockPath = Join-Path $StateRoot "active.lock.json"
if (Test-Path -LiteralPath $LockPath) {
    try {
        $oldLock = Get-Content -LiteralPath $LockPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $oldProcess = Get-Process -Id ([int]$oldLock.pid) -ErrorAction SilentlyContinue
        if ($null -ne $oldProcess) {
            throw "A FAST3 R3 Agent is already running. PID=$($oldLock.pid), RUN_ID=$($oldLock.run_id)"
        }
    } catch {
        if ($_.Exception.Message -like "A FAST3 R3 Agent is already running*") { throw }
    }
    Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
}

$RunId = (Get-Date).ToString("yyyyMMdd_HHmmss")
$RunRoot = Join-Path $RuntimeResultsBase $RunId
$FrozenRunRoot = Join-Path $FrozenResultsBase $RunId
$ScratchRunRoot = Join-Path $Storage.ScratchRoot "fast3\agent_runs\event_factor_cohort_r3\$RunId"
New-Item -ItemType Directory -Force -Path $RunRoot, $FrozenRunRoot, $ScratchRunRoot | Out-Null

$lock = [ordered]@{
    pid = $PID
    run_id = $RunId
    started_at = (Get-Date).ToString("o")
    repo_root = $RepoRoot
    runtime_run_root = $RunRoot
    r1_root = $R1Root
    r2_root = $R2Root
}
$lock | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $LockPath -Encoding UTF8

$RunManifestPath = Join-Path $FrozenRunRoot "launcher_manifest.json"
$EventLogPath = Join-Path $RunRoot "codex_events.jsonl"
$StderrLogPath = Join-Path $RunRoot "codex_stderr.log"
$FinalMessagePath = Join-Path $FrozenRunRoot "codex_final_message.md"
$PreGitPath = Join-Path $RunRoot "git_status_before.txt"
$PostGitPath = Join-Path $RunRoot "git_status_after.txt"
$DiffStatPath = Join-Path $RunRoot "git_diff_stat.txt"
$LauncherSummaryPath = Join-Path $FrozenRunRoot "launcher_summary.json"

$runManifest = [ordered]@{
    run_id = $RunId
    started_at = (Get-Date).ToString("o")
    repo_root = $RepoRoot
    data_root = $DataRoot
    runtime_results_root = $RunRoot
    frozen_results_root = $FrozenRunRoot
    scratch_results_root = $ScratchRunRoot
    r1_root = $R1Root
    r2_root = $R2Root
    prompt_path = $PromptPath
    limits_path = $LimitsPath
    sandbox = "workspace-write"
    approval_policy = "never"
    prompt_mode = "stdin_dash"
    research_scope = "complete_cohort_law_discovery_frozen_model_and_null_audit"
    model_override = $Model
}
$runManifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $RunManifestPath -Encoding UTF8

try {
    Write-Section "FAST3 complete-cohort R3 preflight"
    Write-Host "R1_INVALID_ROOT=$R1Root"
    Write-Host "R2_CONTROL_STOP_ROOT=$R2Root"
    Write-Host "R2_FROZEN_MATCHED_EVENT_COUNT=477456"
    Write-Host "R2_FROZEN_UNMATCHED_EVENT_COUNT=39740"
    Write-Host "R2_TRAINING_ROUND_COUNT=0"

    $codexCommand = Get-Command codex -ErrorAction SilentlyContinue
    if ($null -eq $codexCommand) { throw "Codex CLI was not found. Install it and complete login for the current Windows account." }
    Write-Host "CODEX_PATH=$($codexCommand.Source)"
    & $codexCommand.Source --version
    if ($LASTEXITCODE -ne 0) { throw "codex --version failed with exit code $LASTEXITCODE" }
    Write-Host "CODEX_APPROVAL_ARGUMENT_MODE=GLOBAL_BEFORE_EXEC"
    Write-Host "CODEX_PROMPT_MODE=STDIN_DASH"
    Write-Host "RESEARCH_SCOPE=COMPLETE_COHORT_DISCOVERY_THEN_FROZEN_VALIDATION"
    Write-Host "LONG_TASK_MODE=CHECKPOINTED_FOREGROUND_NO_DETACHED_PROCESS"
    Write-Host "DECISION_AWARE_ARTIFACT_VALIDATION=true"

    if (-not $SkipPreflight) {
        $gitCommand = Get-Command git -ErrorAction SilentlyContinue
        if ($null -ne $gitCommand) {
            Push-Location $RepoRoot
            try { (& $gitCommand.Source status --short 2>&1) | Set-Content -LiteralPath $PreGitPath -Encoding UTF8 }
            finally { Pop-Location }
        } else {
            "git command not found" | Set-Content -LiteralPath $PreGitPath -Encoding UTF8
        }
    }

    $env:FAST3_REPO_ROOT = $RepoRoot
    $env:FAST3_DATA_ROOT = $DataRoot
    $env:FAST3_RESULTS_ROOT = $RunRoot
    $env:FAST3_EXTERNAL_RESULTS_ROOT = $Storage.ResultsRoot
    $env:FAST3_SCRATCH_ROOT = $ScratchRunRoot
    $env:FAST3_FROZEN_ROOT = $FrozenRunRoot
    $env:FAST3_ARCHIVE_ROOT = $Storage.ArchiveRoot
    $env:FAST3_CACHE_ROOT = $Storage.CacheRoot
    $env:FAST3_AGENT_RUN_ID = $RunId
    $env:FAST3_AGENT_LIMITS_PATH = $LimitsPath
    $env:FAST3_R1_INVALID_RUN_ROOT = $R1Root
    $env:FAST3_R2_CONTROL_STOP_ROOT = $R2Root
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) { $env:PYTHONPATH = $RepoRoot }
    else { $env:PYTHONPATH = $RepoRoot + [System.IO.Path]::PathSeparator + $env:PYTHONPATH }

    $instruction = @"
Execute the FAST3 complete-cohort R3 contract now. This is one bounded discovery-then-validation cycle, not an open-ended search. Validate R1 and R2 evidence, quarantine only R1 observed result blocks, freeze the new 14-block schedule before any R3 law result, use the complete UP_FIRST/DOWN_FIRST/NO_EVENT cohort with overlap/class/era weights, recompute factor laws without matched-control deletion, freeze at most 24 stable columns, run the exact six configs and five seeds on the frozen model blocks, freeze one config, then run the five final blocks and five null baselines with actual target-hit exit timestamps. Do not change factors, nine-turn definitions, interactions, models, threshold, Top5, labels, costs, or mapping. R2 matched pairs are post-selection explanatory evidence only. Use FAST3_RESULTS_ROOT for every mutable artifact. Modify only the existing event_factor_law_discovery implementation and optionally one focused test. No detached Python, canonical writes, Git actions, or Broker actions. A legal early stop must still write the common summary/report artifacts and explicit NOT_RUN fields. End with one allowed decision and the required key-value summary.
"@
    $contractText = Get-Content -LiteralPath $PromptPath -Raw -Encoding UTF8
    $combinedPrompt = $instruction + "`r`n`r`n--- BEGIN FAST3 COHORT R3 CONTRACT ---`r`n" +
        $contractText + "`r`n--- END FAST3 COHORT R3 CONTRACT ---`r`n"

    $codexArgs = @(
        "--ask-for-approval", "never",
        "exec", "--json", "--sandbox", "workspace-write",
        "--output-last-message", $FinalMessagePath
    )
    if (-not [string]::IsNullOrWhiteSpace($Model)) { $codexArgs += @("--model", $Model) }
    $codexArgs += "-"

    Write-Section "Start FAST3 complete-cohort R3 Agent"
    Write-Host "RUN_ID=$RunId"
    Write-Host "RUNTIME_RESULTS_ROOT=$RunRoot"
    Write-Host "FROZEN_RESULTS_ROOT=$FrozenRunRoot"
    Write-Host "CODEX_STDERR_LOG=$StderrLogPath"
    Write-Host ""

    Push-Location $RepoRoot
    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $combinedPrompt | & $codexCommand.Source @codexArgs 2> $StderrLogPath |
            Tee-Object -FilePath $EventLogPath
        $CodexExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
        Pop-Location
    }

    Write-Section "Collect and synchronize R3 results"
    $gitCommand = Get-Command git -ErrorAction SilentlyContinue
    if ($null -ne $gitCommand) {
        Push-Location $RepoRoot
        try {
            (& $gitCommand.Source status --short 2>&1) | Set-Content -LiteralPath $PostGitPath -Encoding UTF8
            (& $gitCommand.Source diff --stat 2>&1) | Set-Content -LiteralPath $DiffStatPath -Encoding UTF8
        } finally { Pop-Location }
    }

    $limitsObject = Get-Content -LiteralPath $LimitsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $SummaryPath = Join-Path $RunRoot "fast3_event_factor_r3_summary.json"
    $FinalDecision = $null
    $SummaryReadable = $false
    if (Test-Path -LiteralPath $SummaryPath -PathType Leaf) {
        try {
            $resultSummary = Get-Content -LiteralPath $SummaryPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $FinalDecision = [string]$resultSummary.FINAL_DECISION
            $SummaryReadable = $true
        } catch {
            $SummaryReadable = $false
        }
    }

    $RequiredArtifacts = @($limitsObject.required_artifacts_common)
    if ($SummaryReadable -and -not [string]::IsNullOrWhiteSpace($FinalDecision)) {
        $decisionProperty = $limitsObject.required_artifacts_by_decision.PSObject.Properties[$FinalDecision]
        if ($null -eq $decisionProperty) {
            $SummaryReadable = $false
        } else {
            $RequiredArtifacts += @($decisionProperty.Value)
        }
    }

    $RequiredArtifacts = @($RequiredArtifacts | Select-Object -Unique)
    $artifactState = [ordered]@{}
    foreach ($name in $RequiredArtifacts) {
        $artifactState[$name] = Test-Path -LiteralPath (Join-Path $RunRoot $name) -PathType Leaf
    }
    $AllRequiredArtifactsPresent = $SummaryReadable -and -not ($artifactState.Values -contains $false)

    $summary = [ordered]@{
        launcher_status = if ($CodexExitCode -eq 0) { "CODEX_EXITED_ZERO" } else { "CODEX_EXITED_NONZERO" }
        codex_exit_code = $CodexExitCode
        run_id = $RunId
        finished_at = (Get-Date).ToString("o")
        repo_root = $RepoRoot
        runtime_results_root = $RunRoot
        frozen_results_root = $FrozenRunRoot
        r1_root = $R1Root
        r2_root = $R2Root
        final_decision = $FinalDecision
        summary_readable = $SummaryReadable
        decision_aware_required_artifacts = $artifactState
        all_required_artifacts_present = $AllRequiredArtifactsPresent
        final_message_path = $FinalMessagePath
        event_log_path = $EventLogPath
        stderr_log_path = $StderrLogPath
    }
    $summary | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $LauncherSummaryPath -Encoding UTF8

    Write-Host "CODEX_EXIT_CODE=$CodexExitCode"
    Write-Host "FINAL_DECISION=$FinalDecision"
    Write-Host "SUMMARY_READABLE=$($SummaryReadable.ToString().ToLowerInvariant())"
    Write-Host "ALL_REQUIRED_ARTIFACTS_PRESENT=$($AllRequiredArtifactsPresent.ToString().ToLowerInvariant())"
    Write-Host "RUNTIME_RESULTS_ROOT=$RunRoot"
    Write-Host "FROZEN_RESULTS_ROOT=$FrozenRunRoot"
    Write-Host "FINAL_MESSAGE_PATH=$FinalMessagePath"
    Write-Host "LAUNCHER_SUMMARY_PATH=$LauncherSummaryPath"

    if (Test-Path -LiteralPath $FinalMessagePath -PathType Leaf) {
        Write-Section "Codex final message"
        Get-Content -LiteralPath $FinalMessagePath -Encoding UTF8
    }

    if ($CodexExitCode -ne 0) { exit $CodexExitCode }
    if (-not $SummaryReadable) {
        Write-Warning "Codex exited zero but the R3 summary/decision is missing, unreadable, or not allowed."
        exit 3
    }
    if (-not $AllRequiredArtifactsPresent) {
        Write-Warning "Codex exited zero but the decision-aware R3 artifact set is incomplete."
        exit 3
    }
    exit 0
}
finally {
    Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
}
