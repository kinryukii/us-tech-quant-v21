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

function Resolve-FullPath([string]$PathValue) {
    return [System.IO.Path]::GetFullPath($PathValue)
}

$RepoRoot = Resolve-FullPath $RepoRoot
$DataRoot = Resolve-FullPath $DataRoot
. (Join-Path $PSScriptRoot "fast3_storage_contract_r1.ps1")
$Storage = Resolve-Fast3StorageContract -RepoRoot $RepoRoot -ExternalResultsRoot $ExternalResultsRoot -CacheRoot $CacheRoot

if (-not (Test-Path -LiteralPath $RepoRoot -PathType Container)) { throw "RepoRoot does not exist: $RepoRoot" }
if (-not (Test-Path -LiteralPath $DataRoot -PathType Container)) { throw "DataRoot does not exist: $DataRoot" }

$PromptPath = Join-Path $RepoRoot "docs\fast3\agent\FAST3_EVENT_FACTOR_LAW_DISCOVERY_AGENT.md"
$LimitsPath = Join-Path $RepoRoot "config\fast3\agent\FAST3_EVENT_FACTOR_LAW_DISCOVERY_LIMITS.json"
$StateRoot = Join-Path $Storage.CacheRoot "runtime_locks\fast3\agent\event_factor_law_discovery"
$RuntimeResultsBase = Join-Path $Storage.RuntimeRoot "fast3\agent_runs\event_factor_law_discovery"
$FrozenResultsBase = Join-Path $Storage.FrozenRoot "fast3\agent_runs\event_factor_law_discovery"

foreach ($required in @($PromptPath, $LimitsPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required deployed file is missing: $required" }
}

New-Item -ItemType Directory -Force -Path $StateRoot, $RuntimeResultsBase, $FrozenResultsBase | Out-Null

$LockPath = Join-Path $StateRoot "active.lock.json"
if (Test-Path -LiteralPath $LockPath) {
    try {
        $oldLock = Get-Content -LiteralPath $LockPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $oldProcess = Get-Process -Id ([int]$oldLock.pid) -ErrorAction SilentlyContinue
        if ($null -ne $oldProcess) { throw "A FAST3 event-factor Agent is already running. PID=$($oldLock.pid), RUN_ID=$($oldLock.run_id)" }
    } catch {
        if ($_.Exception.Message -like "A FAST3 event-factor Agent is already running*") { throw }
    }
    Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
}

$RunId = (Get-Date).ToString("yyyyMMdd_HHmmss")
$RunRoot = Join-Path $RuntimeResultsBase $RunId
$FrozenRunRoot = Join-Path $FrozenResultsBase $RunId
$ScratchRunRoot = Join-Path $Storage.ScratchRoot "fast3\agent_runs\event_factor_law_discovery\$RunId"
New-Item -ItemType Directory -Force -Path $RunRoot, $FrozenRunRoot, $ScratchRunRoot | Out-Null

$lock = [ordered]@{
    pid = $PID
    run_id = $RunId
    started_at = (Get-Date).ToString("o")
    repo_root = $RepoRoot
    runtime_run_root = $RunRoot
}
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
    run_id = $RunId
    started_at = (Get-Date).ToString("o")
    repo_root = $RepoRoot
    data_root = $DataRoot
    runtime_results_root = $RunRoot
    frozen_results_root = $FrozenRunRoot
    scratch_results_root = $ScratchRunRoot
    prompt_path = $PromptPath
    limits_path = $LimitsPath
    sandbox = "workspace-write"
    approval_policy = "never"
    prompt_mode = "stdin_dash"
    model_override = $Model
}
$runManifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $RunManifestPath -Encoding UTF8

try {
    Write-Section "FAST3 event-factor Agent preflight"

    $codexCommand = Get-Command codex -ErrorAction SilentlyContinue
    if ($null -eq $codexCommand) { throw "Codex CLI was not found. Install it and complete login for the current Windows account." }
    Write-Host "CODEX_PATH=$($codexCommand.Source)"
    & $codexCommand.Source --version
    if ($LASTEXITCODE -ne 0) { throw "codex --version failed with exit code $LASTEXITCODE" }
    Write-Host "CODEX_APPROVAL_ARGUMENT_MODE=GLOBAL_BEFORE_EXEC"
    Write-Host "CODEX_PROMPT_MODE=STDIN_DASH"
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
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) { $env:PYTHONPATH = $RepoRoot }
    else { $env:PYTHONPATH = $RepoRoot + [System.IO.Path]::PathSeparator + $env:PYTHONPATH }

    $instruction = @"
Execute the complete FAST3 event-centered factor-law discovery contract below now in the current repository. Do not merely propose a plan. Implement and run real data in bounded checkpointed foreground stages. Repeated training and continuous-time random backtests are required, but only inside the frozen round, factor, configuration, and fresh-block budgets. Never reuse an observed audit block, never tune after the final audit, and never expand factor families after Round 1. Use FAST3_RESULTS_ROOT for every run artifact. Do not spawn detached/background Python processes, do not commit/stage/push, and do not write to the external canonical data root. Continue through ordinary failures until an allowed explicit stop decision is reached, then provide the required final key-value summary.
"@
    $contractText = Get-Content -LiteralPath $PromptPath -Raw -Encoding UTF8
    $combinedPrompt = $instruction + "`r`n`r`n--- BEGIN FAST3 EVENT-FACTOR CONTRACT ---`r`n" + $contractText + "`r`n--- END FAST3 EVENT-FACTOR CONTRACT ---`r`n"

    $codexArgs = @(
        "--ask-for-approval", "never",
        "exec",
        "--json",
        "--sandbox", "workspace-write",
        "--output-last-message", $FinalMessagePath
    )
    if (-not [string]::IsNullOrWhiteSpace($Model)) { $codexArgs += @("--model", $Model) }
    $codexArgs += "-"

    Write-Section "Start FAST3 event-factor law discovery Agent"
    Write-Host "RUN_ID=$RunId"
    Write-Host "RUNTIME_RESULTS_ROOT=$RunRoot"
    Write-Host "FROZEN_RESULTS_ROOT=$FrozenRunRoot"
    Write-Host "CODEX_STDERR_LOG=$StderrLogPath"
    Write-Host ""

    Push-Location $RepoRoot
    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $combinedPrompt |
            & $codexCommand.Source @codexArgs 2> $StderrLogPath |
            Tee-Object -FilePath $EventLogPath
        $CodexExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
        Pop-Location
    }

    Write-Section "Collect and synchronize results"

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
        launcher_status = if ($CodexExitCode -eq 0) { "CODEX_EXITED_ZERO" } else { "CODEX_EXITED_NONZERO" }
        codex_exit_code = $CodexExitCode
        run_id = $RunId
        finished_at = (Get-Date).ToString("o")
        repo_root = $RepoRoot
        runtime_results_root = $RunRoot
        frozen_results_root = $FrozenRunRoot
        required_artifacts = $artifactState
        all_required_artifacts_present = $AllRequiredArtifactsPresent
        final_message_path = $FinalMessagePath
        event_log_path = $EventLogPath
        stderr_log_path = $StderrLogPath
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
        Write-Warning "Codex exited with code 0, but required event-factor artifacts are incomplete. This run is not complete."
        exit 3
    }
    exit 0
}
finally {
    Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
}
