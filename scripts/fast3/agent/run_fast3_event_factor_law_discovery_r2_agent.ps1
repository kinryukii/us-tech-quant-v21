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

function Resolve-FullPath([string]$PathValue) { return [System.IO.Path]::GetFullPath($PathValue) }

$RepoRoot = Resolve-FullPath $RepoRoot
$DataRoot = Resolve-FullPath $DataRoot
. (Join-Path $PSScriptRoot "fast3_storage_contract_r1.ps1")
$Storage = Resolve-Fast3StorageContract -RepoRoot $RepoRoot -ExternalResultsRoot $ExternalResultsRoot -CacheRoot $CacheRoot
if (-not (Test-Path -LiteralPath $RepoRoot -PathType Container)) { throw "RepoRoot does not exist: $RepoRoot" }
if (-not (Test-Path -LiteralPath $DataRoot -PathType Container)) { throw "DataRoot does not exist: $DataRoot" }

$PromptPath = Join-Path $RepoRoot "docs\fast3\agent\FAST3_EVENT_FACTOR_LAW_DISCOVERY_R2_REPAIR_AGENT.md"
$LimitsPath = Join-Path $RepoRoot "config\fast3\agent\FAST3_EVENT_FACTOR_LAW_DISCOVERY_R2_LIMITS.json"
$StateRoot = Join-Path $Storage.CacheRoot "runtime_locks\fast3\agent\event_factor_law_discovery_r2"
$RuntimeResultsBase = Join-Path $Storage.RuntimeRoot "fast3\agent_runs\event_factor_law_discovery_r2"
$FrozenResultsBase = Join-Path $Storage.FrozenRoot "fast3\agent_runs\event_factor_law_discovery_r2"

foreach ($required in @($PromptPath, $LimitsPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required deployed file is missing: $required" }
}

$R1Runtime = Join-Path $Storage.RuntimeRoot "fast3\agent_runs\event_factor_law_discovery\20260802_184840"
$R1LegacyCompatibility = Join-Path $Storage.LegacyCompatibilityRoot "fast3\event_factor_law_discovery\20260802_184840"
$R1InvalidRoot = if (Test-Path -LiteralPath $R1Runtime -PathType Container) { $R1Runtime } elseif (Test-Path -LiteralPath $R1LegacyCompatibility -PathType Container) { $R1LegacyCompatibility } else { $null }
if ($null -eq $R1InvalidRoot) { throw "Required R1 invalid run 20260802_184840 was not found in approved external storage." }

$R1Required = @(
    "fast3_event_factor_summary.json",
    "FAST3_POST_AUDIT_INTEGRITY.json",
    "FAST3_ROUND_LEDGER.jsonl",
    "FAST3_EVENT_FACTOR_DISCOVERY_CONTRACT.json",
    "FAST3_FACTOR_DICTIONARY.json",
    "fast3_event_ledger.parquet",
    "fast3_random_time_block_results.csv"
)
foreach ($name in $R1Required) {
    $path = Join-Path $R1InvalidRoot $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required R1 repair source is missing: $path" }
}

$r1Summary = Get-Content -LiteralPath (Join-Path $R1InvalidRoot "fast3_event_factor_summary.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$r1Summary.FINAL_DECISION -ne "STOP_IMPLEMENTATION_INVALID") { throw "R1 source does not have the expected invalid decision." }
if ([int]$r1Summary.POST_AUDIT_CONTRACT_INTEGRITY.events_without_matched_control -ne 11888) { throw "R1 unmatched-event count is not the expected frozen value 11888." }

New-Item -ItemType Directory -Force -Path $StateRoot, $RuntimeResultsBase, $FrozenResultsBase | Out-Null
$LockPath = Join-Path $StateRoot "active.lock.json"
if (Test-Path -LiteralPath $LockPath) {
    try {
        $oldLock = Get-Content -LiteralPath $LockPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $oldProcess = Get-Process -Id ([int]$oldLock.pid) -ErrorAction SilentlyContinue
        if ($null -ne $oldProcess) { throw "A FAST3 R2 repair Agent is already running. PID=$($oldLock.pid), RUN_ID=$($oldLock.run_id)" }
    } catch {
        if ($_.Exception.Message -like "A FAST3 R2 repair Agent is already running*") { throw }
    }
    Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
}

$RunId = (Get-Date).ToString("yyyyMMdd_HHmmss")
$RunRoot = Join-Path $RuntimeResultsBase $RunId
$FrozenRunRoot = Join-Path $FrozenResultsBase $RunId
$ScratchRunRoot = Join-Path $Storage.ScratchRoot "fast3\agent_runs\event_factor_law_discovery_r2\$RunId"
New-Item -ItemType Directory -Force -Path $RunRoot, $FrozenRunRoot, $ScratchRunRoot | Out-Null

$lock = [ordered]@{ pid=$PID; run_id=$RunId; started_at=(Get-Date).ToString("o"); repo_root=$RepoRoot; runtime_run_root=$RunRoot; r1_invalid_root=$R1InvalidRoot }
$lock | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $LockPath -Encoding UTF8

$RunManifestPath = Join-Path $FrozenRunRoot "launcher_manifest.json"
$EventLogPath = Join-Path $RunRoot "codex_events.jsonl"
$StderrLogPath = Join-Path $RunRoot "codex_stderr.log"
$FinalMessagePath = Join-Path $FrozenRunRoot "codex_final_message.md"
$PreGitPath = Join-Path $RunRoot "git_status_before.txt"
$PostGitPath = Join-Path $RunRoot "git_status_after.txt"
$DiffStatPath = Join-Path $RunRoot "git_diff_stat.txt"
$LauncherSummaryPath = Join-Path $FrozenRunRoot "launcher_summary.json"

$runManifest = [ordered]@{
    run_id=$RunId; started_at=(Get-Date).ToString("o"); repo_root=$RepoRoot; data_root=$DataRoot
runtime_results_root=$RunRoot; frozen_results_root=$FrozenRunRoot; scratch_results_root=$ScratchRunRoot; r1_invalid_root=$R1InvalidRoot
    prompt_path=$PromptPath; limits_path=$LimitsPath; sandbox="workspace-write"; approval_policy="never"
    prompt_mode="stdin_dash"; repair_scope="restricted_r2_control_and_null_audit"; model_override=$Model
}
$runManifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $RunManifestPath -Encoding UTF8

try {
    Write-Section "FAST3 restricted R2 repair preflight"
    Write-Host "R1_INVALID_ROOT=$R1InvalidRoot"
    Write-Host "R1_FROZEN_UNMATCHED_EVENT_COUNT=11888"

    $codexCommand = Get-Command codex -ErrorAction SilentlyContinue
    if ($null -eq $codexCommand) { throw "Codex CLI was not found. Install it and complete login for the current Windows account." }
    Write-Host "CODEX_PATH=$($codexCommand.Source)"
    & $codexCommand.Source --version
    if ($LASTEXITCODE -ne 0) { throw "codex --version failed with exit code $LASTEXITCODE" }
    Write-Host "CODEX_APPROVAL_ARGUMENT_MODE=GLOBAL_BEFORE_EXEC"
    Write-Host "CODEX_PROMPT_MODE=STDIN_DASH"
    Write-Host "REPAIR_SCOPE=CONTROL_MATCH_INTEGRITY_AND_NULL_ECONOMIC_AUDIT_ONLY"
    Write-Host "LONG_TASK_MODE=CHECKPOINTED_FOREGROUND_NO_DETACHED_PROCESS"

    if (-not $SkipPreflight) {
        $gitCommand = Get-Command git -ErrorAction SilentlyContinue
        if ($null -ne $gitCommand) {
            Push-Location $RepoRoot
            try { (& $gitCommand.Source status --short 2>&1) | Set-Content -LiteralPath $PreGitPath -Encoding UTF8 }
            finally { Pop-Location }
        } else { "git command not found" | Set-Content -LiteralPath $PreGitPath -Encoding UTF8 }
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
    $env:FAST3_R1_INVALID_RUN_ROOT = $R1InvalidRoot
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) { $env:PYTHONPATH = $RepoRoot }
    else { $env:PYTHONPATH = $RepoRoot + [System.IO.Path]::PathSeparator + $env:PYTHONPATH }

    $instruction = @"
Execute the restricted FAST3 R2 repair contract below now. This is not authorization for a new strategy search. Modify only the existing event_factor_law_discovery implementation as explicitly permitted, optionally add one focused test file, and run real data in checkpointed foreground stages. First import and quarantine every R1 observed block, freeze all R2 blocks, diagnose the 11,888 unmatched events, and achieve the frozen 100% control-matching gate before any factor law or model fit. If matching fails, stop before training. Keep the exact R1 factor dictionary, nine-turn definitions, six model configs, five seeds, label, threshold, Top5, ETF mapping, and costs. After one final audit, run the five frozen null-economic baselines and never retrain. Use FAST3_RESULTS_ROOT for all new artifacts and FAST3_R1_INVALID_RUN_ROOT as read-only R1 evidence. Do not create new factor/model subsystems, do not use detached/background Python, do not write canonical data, and do not stage/commit/push. End with one allowed explicit decision and the required key-value summary.
"@
    $contractText = Get-Content -LiteralPath $PromptPath -Raw -Encoding UTF8
    $combinedPrompt = $instruction + "`r`n`r`n--- BEGIN FAST3 RESTRICTED R2 CONTRACT ---`r`n" + $contractText + "`r`n--- END FAST3 RESTRICTED R2 CONTRACT ---`r`n"

    $codexArgs = @(
        "--ask-for-approval", "never",
        "exec", "--json", "--sandbox", "workspace-write",
        "--output-last-message", $FinalMessagePath
    )
    if (-not [string]::IsNullOrWhiteSpace($Model)) { $codexArgs += @("--model", $Model) }
    $codexArgs += "-"

    Write-Section "Start FAST3 restricted R2 repair Agent"
    Write-Host "RUN_ID=$RunId"
Write-Host "RUNTIME_RESULTS_ROOT=$RunRoot"
Write-Host "FROZEN_RESULTS_ROOT=$FrozenRunRoot"
    Write-Host "CODEX_STDERR_LOG=$StderrLogPath"
    Write-Host ""

    Push-Location $RepoRoot
    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $combinedPrompt | & $codexCommand.Source @codexArgs 2> $StderrLogPath | Tee-Object -FilePath $EventLogPath
        $CodexExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
        Pop-Location
    }

    Write-Section "Collect and synchronize R2 results"
    $gitCommand = Get-Command git -ErrorAction SilentlyContinue
    if ($null -ne $gitCommand) {
        Push-Location $RepoRoot
        try {
            (& $gitCommand.Source status --short 2>&1) | Set-Content -LiteralPath $PostGitPath -Encoding UTF8
            (& $gitCommand.Source diff --stat 2>&1) | Set-Content -LiteralPath $DiffStatPath -Encoding UTF8
        } finally { Pop-Location }
    }

    $limitsObject = Get-Content -LiteralPath $LimitsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $RequiredArtifacts = @($limitsObject.required_artifacts)
    $artifactState = [ordered]@{}
    foreach ($name in $RequiredArtifacts) { $artifactState[$name] = Test-Path -LiteralPath (Join-Path $RunRoot $name) -PathType Leaf }
    $AllRequiredArtifactsPresent = -not ($artifactState.Values -contains $false)

    $summary = [ordered]@{
        launcher_status=if ($CodexExitCode -eq 0) { "CODEX_EXITED_ZERO" } else { "CODEX_EXITED_NONZERO" }
        codex_exit_code=$CodexExitCode; run_id=$RunId; finished_at=(Get-Date).ToString("o")
repo_root=$RepoRoot; runtime_results_root=$RunRoot; frozen_results_root=$FrozenRunRoot
        r1_invalid_root=$R1InvalidRoot; required_artifacts=$artifactState
        all_required_artifacts_present=$AllRequiredArtifactsPresent
        final_message_path=$FinalMessagePath; event_log_path=$EventLogPath; stderr_log_path=$StderrLogPath
    }
    $summary | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $LauncherSummaryPath -Encoding UTF8

    Write-Host "CODEX_EXIT_CODE=$CodexExitCode"
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
    if (-not $AllRequiredArtifactsPresent) {
        Write-Warning "Codex exited zero but required R2 repair artifacts are incomplete. This run is not complete."
        exit 3
    }
    exit 0
}
finally {
    Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
}
