[CmdletBinding()]
param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$DataRoot = "D:\us-tech-quant-data",
    [string]$ExternalResultsRoot = "D:\us-tech-quant-results",
    [string]$CacheRoot = "D:\us-tech-quant-cache",
    [string]$Model = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Section([string]$Text) {
    Write-Host ""
    Write-Host ("=" * 78)
    Write-Host (" " + $Text)
    Write-Host ("=" * 78)
}

$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
$DataRoot = [IO.Path]::GetFullPath($DataRoot)
. (Join-Path $PSScriptRoot "fast3_storage_contract_r1.ps1")
$Storage = Resolve-Fast3StorageContract -RepoRoot $RepoRoot -ExternalResultsRoot $ExternalResultsRoot -CacheRoot $CacheRoot
$PromptPath = Join-Path $RepoRoot "docs\fast3\agent\FAST3_R3_ECONOMIC_INTEGRITY_AUDIT_AGENT.md"
$LimitsPath = Join-Path $RepoRoot "config\fast3\agent\FAST3_R3_ECONOMIC_INTEGRITY_AUDIT_LIMITS.json"
foreach ($p in @($PromptPath,$LimitsPath)) {
    if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { throw "Required deployed file missing: $p" }
}

$R3External = Join-Path $Storage.RuntimeRoot "fast3\agent_runs\event_factor_cohort_r3\20260802_211307"
$R3LegacyCompatibility = Join-Path $Storage.LegacyCompatibilityRoot "fast3\event_factor_cohort_r3\20260802_211307"
$R3Root = if (Test-Path -LiteralPath $R3External -PathType Container) {
    $R3External
} elseif (Test-Path -LiteralPath $R3LegacyCompatibility -PathType Container) {
    $R3LegacyCompatibility
} else {
    throw "Frozen R3 run was not found in approved external storage: $R3External or $R3LegacyCompatibility"
}

$summaryPath = Join-Path $R3Root "fast3_event_factor_r3_summary.json"
if (-not (Test-Path -LiteralPath $summaryPath -PathType Leaf)) { throw "Frozen R3 summary missing: $summaryPath" }
$r3 = Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$r3.RUN_ID -ne "20260802_211307" -or
    [string]$r3.FINAL_DECISION -ne "STOP_NO_SIGNIFICANT_GAIN_OVER_LEGACY" -or
    [int]$r3.ACCEPTED_TRADE_COUNT -ne 696) {
    throw "Frozen R3 identity mismatch."
}

$requiredInputs = @(
    "fast3_event_factor_r3_summary.json",
    "FAST3_EVENT_FACTOR_R3_REPORT.md",
    "FAST3_MODEL_FREEZE.json",
    "FAST3_FACTOR_LAW_FREEZE.json",
    "FAST3_RANDOM_BLOCK_SCHEDULE.json",
    "FAST3_EXECUTION_SANITY_AUDIT.json",
    "fast3_event_predictions.parquet",
    "fast3_final_audit_results.csv",
    "fast3_null_model_results.csv"
)
foreach ($name in $requiredInputs) {
    $p = Join-Path $R3Root $name
    if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { throw "Frozen R3 input missing: $p" }
}

$StateRoot = Join-Path $Storage.CacheRoot "runtime_locks\fast3\agent\r3_economic_integrity_audit"
$RuntimeResultsBase = Join-Path $Storage.RuntimeRoot "fast3\agent_runs\r3_economic_integrity_audit"
$FrozenResultsBase = Join-Path $Storage.FrozenRoot "fast3\agent_runs\r3_economic_integrity_audit"
New-Item -ItemType Directory -Force -Path $StateRoot,$RuntimeResultsBase,$FrozenResultsBase | Out-Null
$lock = Join-Path $StateRoot "active.lock.json"

if (Test-Path -LiteralPath $lock) {
    try {
        $old = Get-Content -LiteralPath $lock -Raw -Encoding UTF8 | ConvertFrom-Json
        if (Get-Process -Id ([int]$old.pid) -ErrorAction SilentlyContinue) {
            throw "R3 economic audit is already running. PID=$($old.pid)"
        }
    } catch {
        if ($_.Exception.Message -like "R3 economic audit is already running*") { throw }
    }
    Remove-Item -LiteralPath $lock -Force -ErrorAction SilentlyContinue
}

$RunId = (Get-Date).ToString("yyyyMMdd_HHmmss")
$RunRoot = Join-Path $RuntimeResultsBase $RunId
$FrozenRunRoot = Join-Path $FrozenResultsBase $RunId
$ScratchRunRoot = Join-Path $Storage.ScratchRoot "fast3\agent_runs\r3_economic_integrity_audit\$RunId"
New-Item -ItemType Directory -Force -Path $RunRoot,$FrozenRunRoot,$ScratchRunRoot | Out-Null
[ordered]@{pid=$PID;run_id=$RunId;started_at=(Get-Date).ToString("o");run_root=$RunRoot;source_r3_root=$R3Root} |
    ConvertTo-Json | Set-Content -LiteralPath $lock -Encoding UTF8

$events = Join-Path $RunRoot "codex_events.jsonl"
$stderr = Join-Path $RunRoot "codex_stderr.log"
$finalMessage = Join-Path $FrozenRunRoot "codex_final_message.md"
$before = Join-Path $RunRoot "git_status_before.txt"
$after = Join-Path $RunRoot "git_status_after.txt"
$launcherSummary = Join-Path $FrozenRunRoot "launcher_summary.json"

try {
    Section "FAST3 frozen R3 economic-integrity audit preflight"
    Write-Host "SOURCE_R3_ROOT=$R3Root"
    Write-Host "SOURCE_R3_RUN_ID=20260802_211307"
    Write-Host "SOURCE_R3_DECISION=STOP_NO_SIGNIFICANT_GAIN_OVER_LEGACY"
    Write-Host "FROZEN_ACCEPTED_RECORD_COUNT=696"
    Write-Host "MODEL_OR_FACTOR_RETRAINING_ALLOWED=false"
    Write-Host "REPO_CODE_CHANGE_ALLOWED=false"
    Write-Host "CANONICAL_WRITE_ALLOWED=false"
    Write-Host "CONFIRMATION_ROWS_ALLOWED=0"

    $codex = Get-Command codex -ErrorAction SilentlyContinue
    if ($null -eq $codex) { throw "Codex CLI not found." }
    & $codex.Source --version
    if ($LASTEXITCODE -ne 0) { throw "codex --version failed." }

    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($null -ne $git) {
        Push-Location $RepoRoot
        try { (& $git.Source status --short 2>&1) | Set-Content -LiteralPath $before -Encoding UTF8 }
        finally { Pop-Location }
    } else {
        "git unavailable" | Set-Content -LiteralPath $before -Encoding UTF8
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
    $env:FAST3_R3_SOURCE_ROOT = $R3Root
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $env:LOKY_MAX_CPU_COUNT = "1"

    $instruction = @"
Execute the frozen FAST3 R3 economic-integrity post-audit now. Read the contract and limits exactly. Do not run or import any function that fits, refits, selects, or regenerates model predictions. Do not modify repository code. Any temporary Python must be written only inside FAST3_RESULTS_ROOT and run in the foreground. Validate and hash the exact R3 inputs, reconstruct only frozen accepted records, audit seed duplicates, verify target-hit timestamps against read-only ETF minute bars, run only the five pre-registered execution stresses, produce subgroup decomposition and block/natural-week/unique-trade clustered uncertainty, then apply the exact audit decision order. Preserve SOURCE_R3_DECISION=STOP_NO_SIGNIFICANT_GAIN_OVER_LEGACY under every outcome.
"@
    $contract = Get-Content -LiteralPath $PromptPath -Raw -Encoding UTF8
    $combined = $instruction + "`r`n`r`n--- BEGIN AUDIT CONTRACT ---`r`n" + $contract + "`r`n--- END AUDIT CONTRACT ---`r`n"
    $args = @(
        "--ask-for-approval","never",
        "exec","--json","--sandbox","workspace-write",
        "--output-last-message",$finalMessage
    )
    if (-not [string]::IsNullOrWhiteSpace($Model)) { $args += @("--model",$Model) }
    $args += "-"

    Section "Start read-only post-audit Agent"
    Write-Host "AUDIT_RUN_ID=$RunId"
Write-Host "RUNTIME_RESULTS_ROOT=$RunRoot"
Write-Host "FROZEN_RESULTS_ROOT=$FrozenRunRoot"

    Push-Location $RepoRoot
    $oldPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $combined | & $codex.Source @args 2> $stderr | Tee-Object -FilePath $events
        $codexExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $oldPreference
        Pop-Location
    }

    if ($null -ne $git) {
        Push-Location $RepoRoot
        try { (& $git.Source status --short 2>&1) | Set-Content -LiteralPath $after -Encoding UTF8 }
        finally { Pop-Location }
    } else {
        "git unavailable" | Set-Content -LiteralPath $after -Encoding UTF8
    }

    $beforeText = (Get-Content -LiteralPath $before -Raw -Encoding UTF8)
    $afterText = (Get-Content -LiteralPath $after -Raw -Encoding UTF8)
    $repoStatusUnchanged = $beforeText -eq $afterText

    $limits = Get-Content -LiteralPath $LimitsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $auditSummaryPath = Join-Path $RunRoot "fast3_r3_post_audit_summary.json"
    $summaryReadable = $false
    $decision = $null
    if (Test-Path -LiteralPath $auditSummaryPath -PathType Leaf) {
        try {
            $auditSummary = Get-Content -LiteralPath $auditSummaryPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $decision = [string]$auditSummary.FINAL_DECISION
            $summaryReadable = @($limits.decision_order) -contains $decision
        } catch { $summaryReadable = $false }
    }

    $artifactState = [ordered]@{}
    foreach ($name in @($limits.required_artifacts)) {
        $artifactState[$name] = Test-Path -LiteralPath (Join-Path $RunRoot $name) -PathType Leaf
    }
    $allArtifacts = $summaryReadable -and -not ($artifactState.Values -contains $false)
    $launcher = [ordered]@{
        codex_exit_code=$codexExit
        audit_run_id=$RunId
        source_r3_root=$R3Root
        final_decision=$decision
        summary_readable=$summaryReadable
        repo_status_unchanged=$repoStatusUnchanged
        all_required_artifacts_present=$allArtifacts
        artifact_state=$artifactState
runtime_results_root=$RunRoot
frozen_results_root=$FrozenRunRoot
        final_message_path=$finalMessage
    }
    $launcher | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $launcherSummary -Encoding UTF8

    Section "Audit collection"
    Write-Host "CODEX_EXIT_CODE=$codexExit"
    Write-Host "FINAL_DECISION=$decision"
    Write-Host "SUMMARY_READABLE=$($summaryReadable.ToString().ToLowerInvariant())"
    Write-Host "REPO_STATUS_UNCHANGED=$($repoStatusUnchanged.ToString().ToLowerInvariant())"
    Write-Host "ALL_REQUIRED_ARTIFACTS_PRESENT=$($allArtifacts.ToString().ToLowerInvariant())"
Write-Host "RUNTIME_RESULTS_ROOT=$RunRoot"
Write-Host "FROZEN_RESULTS_ROOT=$FrozenRunRoot"

    if (Test-Path -LiteralPath $finalMessage -PathType Leaf) {
        Section "Codex final message"
        Get-Content -LiteralPath $finalMessage -Encoding UTF8
    }

    if ($codexExit -ne 0) { exit $codexExit }
    if (-not $repoStatusUnchanged) {
        Write-Warning "Repository status changed during a read-only audit."
        exit 4
    }
    if (-not $summaryReadable -or -not $allArtifacts) { exit 3 }
    exit 0
}
finally {
    Remove-Item -LiteralPath $lock -Force -ErrorAction SilentlyContinue
}
