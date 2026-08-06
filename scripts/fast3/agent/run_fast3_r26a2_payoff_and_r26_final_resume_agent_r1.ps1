[CmdletBinding()]
param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$DataRoot = "D:\us-tech-quant-data",
    [string]$ResultsRoot = "D:\us-tech-quant-results",
    [string]$CacheRoot = "D:\us-tech-quant-cache",
    [string]$R3SourceRoot = "D:\us-tech-quant-results\fast3\agent_runs\event_factor_cohort_r3\20260803_181405",
    [string]$R3AuditRoot = "D:\us-tech-quant-results\fast3\agent_runs\r3_economic_integrity_audit\20260803_183906",
    [string]$CompleteLedgerPath = "D:\us-tech-quant-results\fast3\agent_runs\event_factor_law_discovery\20260802_184840\fast3_event_ledger.parquet",
    [string]$R24ControlFrozenRoot = "D:\us-tech-quant-results\frozen\fast3\r4_two_stage_direction\20260803_183950",
    [string]$R25FrozenRoot = "D:\us-tech-quant-results\frozen\fast3\r25_asymmetric_direction\r25_indexfix_20260803_192003",
    [string]$R26FailedFrozenRoot = "D:\us-tech-quant-results\frozen\fast3\r26_economic_value_gate\20260803_201228_r3",
    [string]$R26A1FailedFrozenRoot = "D:\us-tech-quant-results\frozen\fast3\r26a_executable_payoff_ledger\20260803_233024",
    [string]$CoverageAttributionRoot = "D:\us-tech-quant-results\frozen\fast3\r26a_coverage_attribution\20260804_coverage_attribution_r2",
    [string]$PackageRoot,
    [ValidateRange(0,2)]
    [int]$MaxFocusedRepairs = 2
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Section([string]$Title) {
    Write-Host ""
    Write-Host ("=" * 96)
    Write-Host " $Title"
    Write-Host ("=" * 96)
}

function Assert-Path([string]$Path, [string]$Code, [switch]$Leaf) {
    $ok = if ($Leaf) {
        Test-Path -LiteralPath $Path -PathType Leaf
    } else {
        Test-Path -LiteralPath $Path
    }
    if (-not $ok) { throw "$Code`:$Path" }
}

function Get-RelativePathSafe([string]$Root, [string]$Path) {
    $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    $pathFull = [System.IO.Path]::GetFullPath($Path)
    if ($pathFull.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $pathFull.Substring($rootFull.Length)
    }
    return $pathFull
}

function Get-TreeMetadataHash([string]$Root) {
    $rows = @()
    if (Test-Path -LiteralPath $Root) {
        $files = @(Get-ChildItem -LiteralPath $Root -Force -File -Recurse -ErrorAction Stop)
        foreach ($file in $files) {
            $rows += [ordered]@{
                relative_path = Get-RelativePathSafe -Root $Root -Path $file.FullName
                length = [int64]$file.Length
                last_write_utc_ticks = [int64]$file.LastWriteTimeUtc.Ticks
                attributes = [string]$file.Attributes
            }
        }
    }
    $json = $rows | Sort-Object relative_path | ConvertTo-Json -Depth 5 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes([string]$json)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-LocalResultsInventory([string]$RepoRoot) {
    $root = Join-Path $RepoRoot ".local_results"
    if (-not (Test-Path -LiteralPath $root)) { return @() }
    return @(
        Get-ChildItem -LiteralPath $root -Force -Recurse -ErrorAction SilentlyContinue |
            ForEach-Object { Get-RelativePathSafe -Root $RepoRoot -Path $_.FullName }
    )
}

function Get-UntrackedInventory([string]$RealGit, [string]$RepoRoot) {
    if ([string]::IsNullOrWhiteSpace($RealGit)) { return @() }
    $output = & $RealGit -C $RepoRoot ls-files --others --exclude-standard 2>$null
    if ($LASTEXITCODE -ne 0) { throw "READ_ONLY_GIT_UNTRACKED_INVENTORY_FAILED" }
    return @($output | ForEach-Object { [string]$_ })
}

function Test-UntrackedPathsPreserved([string[]]$Before, [string]$RepoRoot) {
    foreach ($relative in $Before) {
        $native = $relative.Replace("/", "\")
        if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot $native))) {
            return $false
        }
    }
    return $true
}

if ([string]::IsNullOrWhiteSpace($PackageRoot)) {
    $PackageRoot = Split-Path -Parent (
        Split-Path -Parent (
            Split-Path -Parent (
                Split-Path -Parent $PSCommandPath
            )
        )
    )
}

$RepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)
$DataRoot = [System.IO.Path]::GetFullPath($DataRoot)
$ResultsRoot = [System.IO.Path]::GetFullPath($ResultsRoot)
$CacheRoot = [System.IO.Path]::GetFullPath($CacheRoot)
$R3SourceRoot = [System.IO.Path]::GetFullPath($R3SourceRoot)
$R3AuditRoot = [System.IO.Path]::GetFullPath($R3AuditRoot)
$CompleteLedgerPath = [System.IO.Path]::GetFullPath($CompleteLedgerPath)
$R24ControlFrozenRoot = [System.IO.Path]::GetFullPath($R24ControlFrozenRoot)
$R25FrozenRoot = [System.IO.Path]::GetFullPath($R25FrozenRoot)
$R26FailedFrozenRoot = [System.IO.Path]::GetFullPath($R26FailedFrozenRoot)
$R26A1FailedFrozenRoot = [System.IO.Path]::GetFullPath($R26A1FailedFrozenRoot)
$CoverageAttributionRoot = [System.IO.Path]::GetFullPath($CoverageAttributionRoot)
$PackageRoot = [System.IO.Path]::GetFullPath($PackageRoot)
$env:PYTHONPATH = Join-Path $RepoRoot "fast3\src"

$RunId = Get-Date -Format "yyyyMMdd_HHmmss"
$CanonicalRoot = Join-Path $DataRoot "fast3\moomoo_24h_1m\canonical"
$AgentRuntimeRoot = Join-Path $ResultsRoot "runtime\fast3\r26a2_r26_agent_launcher\$RunId"
$AgentScratchRoot = Join-Path $ResultsRoot "scratch\fast3\r26a2_r26_agent_launcher\$RunId"
$AgentFrozenRoot = Join-Path $ResultsRoot "frozen\fast3\r26a2_r26_agent_launcher\$RunId"
$AgentArchiveRoot = Join-Path $ResultsRoot "archive\fast3\r26a2_r26_agent_launcher\$RunId"
$AgentCacheRoot = Join-Path $CacheRoot "fast3\r26a2_r26_agent_launcher\$RunId"
$TaskTemplate = Join-Path $PackageRoot "config\FAST3_R26A2_CALENDAR_AWARE_PAYOFF_AND_R26_FINAL_RESUME_TASK_R1.md"
$TaskPath = Join-Path $AgentRuntimeRoot "CODEX_TASK.md"
$EventsPath = Join-Path $AgentRuntimeRoot "codex_events.jsonl"
$StderrPath = Join-Path $AgentRuntimeRoot "codex_stderr.log"
$FinalMessagePath = Join-Path $AgentRuntimeRoot "codex_final_message.md"
$LauncherSummaryPath = Join-Path $AgentFrozenRoot "R26A2_R26_AGENT_LAUNCHER_SUMMARY.json"
$LauncherReportPath = Join-Path $AgentFrozenRoot "R26A2_R26_AGENT_LAUNCHER_REPORT.md"
$CanonicalBeforePath = Join-Path $AgentFrozenRoot "canonical_metadata_before.sha256"
$CanonicalAfterPath = Join-Path $AgentFrozenRoot "canonical_metadata_after.sha256"
$BlockedBin = Join-Path $AgentCacheRoot "blocked_bin"
$GitGuardPath = Join-Path $BlockedBin "git_guard.ps1"
$GitCmdPath = Join-Path $BlockedBin "git.cmd"
$CodexCmdPath = Join-Path $AgentCacheRoot "run_codex_agent.cmd"

New-Item -ItemType Directory -Force -Path `
    $AgentRuntimeRoot, $AgentScratchRoot, $AgentFrozenRoot, $AgentArchiveRoot, `
    $AgentCacheRoot, $BlockedBin | Out-Null

$summary = [ordered]@{
    RUN_ID = $RunId
    AGENT_LAUNCHER_STATUS = "STARTED"
    CODEX_PERMISSION_MODE = $null
    CODEX_EXIT_CODE = $null
    CANONICAL_METADATA_UNCHANGED = $false
    NEW_LOCAL_RESULTS_WRITE_COUNT = $null
    UNTRACKED_FILE_PRESERVATION_PASS = $false
    GIT_MUTATION_COMMAND_BLOCK_ACTIVE = $false
    GIT_MUTATION_COMMAND_PERFORMED = $false
    FINAL_DECISION = "STOP_R26A2_R26_AGENT_NOT_COMPLETED"
    FINAL_MESSAGE_PATH = $FinalMessagePath
    FROZEN_ROOT = $AgentFrozenRoot
    ARCHIVE_ROOT = $AgentArchiveRoot
    CACHE_ROOT = $AgentCacheRoot
}

$RealGit = $null
$UntrackedBefore = @()
$LocalResultsBefore = @()
$CanonicalBefore = $null
$failure = $null

try {
    Write-Section "FAST3 R26A2 calendar-aware payoff / final R26 preflight"

    Assert-Path $RepoRoot "REPO_ROOT_MISSING"
    Assert-Path $CanonicalRoot "CANONICAL_ROOT_MISSING"
    Assert-Path $R3SourceRoot "R3_SOURCE_ROOT_MISSING"
    Assert-Path $R3AuditRoot "R3_AUDIT_ROOT_MISSING"
    Assert-Path $CompleteLedgerPath "COMPLETE_LEDGER_MISSING" -Leaf
    Assert-Path $R24ControlFrozenRoot "R24_CONTROL_FROZEN_ROOT_MISSING"
    Assert-Path $R25FrozenRoot "R25_FROZEN_ROOT_MISSING"
    Assert-Path $R26FailedFrozenRoot "R26_FAILED_FROZEN_ROOT_MISSING"
    Assert-Path $R26A1FailedFrozenRoot "R26A1_FAILED_FROZEN_ROOT_MISSING"
    Assert-Path $CoverageAttributionRoot "COVERAGE_ATTRIBUTION_ROOT_MISSING"
    Assert-Path $TaskTemplate "TASK_TEMPLATE_MISSING" -Leaf

    $codex = Get-Command codex -ErrorAction SilentlyContinue
    if ($null -eq $codex) { throw "CODEX_CLI_NOT_FOUND" }

    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($null -ne $git) {
        $RealGit = [string]$git.Source
        $env:FAST3_REAL_GIT = $RealGit
        $UntrackedBefore = Get-UntrackedInventory -RealGit $RealGit -RepoRoot $RepoRoot

        $gitGuard = @'
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$GitArgs
)
$ErrorActionPreference = "Stop"
$realGit = $env:FAST3_REAL_GIT
if ([string]::IsNullOrWhiteSpace($realGit)) {
    Write-Error "FAST3_REAL_GIT_NOT_SET"
    exit 98
}
$skipNext = $false
$verb = $null
for ($i = 0; $i -lt $GitArgs.Count; $i++) {
    $arg = [string]$GitArgs[$i]
    if ($skipNext) {
        $skipNext = $false
        continue
    }
    if ($arg -in @("-C", "-c", "--git-dir", "--work-tree", "--namespace")) {
        $skipNext = $true
        continue
    }
    if ($arg.StartsWith("-")) { continue }
    $verb = $arg.ToLowerInvariant()
    break
}
$blocked = @(
    "add", "clean", "reset", "stash", "checkout", "restore", "commit", "push",
    "rm", "mv", "switch", "merge", "rebase", "cherry-pick", "revert", "tag",
    "branch", "worktree", "submodule", "gc", "prune"
)
if ($null -ne $verb -and $blocked -contains $verb) {
    [Console]::Error.WriteLine("FAST3_GIT_MUTATION_BLOCKED:" + $verb)
    exit 97
}
& $realGit @GitArgs
exit $LASTEXITCODE
'@
        [System.IO.File]::WriteAllText(
            $GitGuardPath,
            $gitGuard,
            [System.Text.UTF8Encoding]::new($false)
        )
        $gitCmd = '@echo off' + "`r`n" +
            'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0git_guard.ps1" %*' +
            "`r`nexit /b %ERRORLEVEL%`r`n"
        [System.IO.File]::WriteAllText(
            $GitCmdPath,
            $gitCmd,
            [System.Text.ASCIIEncoding]::new()
        )
        $env:PATH = $BlockedBin + ";" + $env:PATH
        $summary.GIT_MUTATION_COMMAND_BLOCK_ACTIVE = $true
    }

    $LocalResultsBefore = Get-LocalResultsInventory -RepoRoot $RepoRoot
    $CanonicalBefore = Get-TreeMetadataHash -Root $CanonicalRoot
    [System.IO.File]::WriteAllText(
        $CanonicalBeforePath,
        $CanonicalBefore,
        [System.Text.ASCIIEncoding]::new()
    )

    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONPYCACHEPREFIX = Join-Path $AgentCacheRoot "pycache"
    $env:TMP = Join-Path $AgentCacheRoot "tmp"
    $env:TEMP = $env:TMP
    New-Item -ItemType Directory -Force -Path $env:TMP, $env:PYTHONPYCACHEPREFIX |
        Out-Null

    $task = Get-Content -LiteralPath $TaskTemplate -Raw -Encoding UTF8
    $replacements = [ordered]@{
        "{{REPO_ROOT}}" = $RepoRoot
        "{{DATA_ROOT}}" = $DataRoot
        "{{RESULTS_ROOT}}" = $ResultsRoot
        "{{CACHE_ROOT}}" = $CacheRoot
        "{{R3_SOURCE_ROOT}}" = $R3SourceRoot
        "{{R3_AUDIT_ROOT}}" = $R3AuditRoot
        "{{COMPLETE_LEDGER_PATH}}" = $CompleteLedgerPath
        "{{R24_CONTROL_FROZEN_ROOT}}" = $R24ControlFrozenRoot
        "{{R25_FROZEN_ROOT}}" = $R25FrozenRoot
        "{{R26_FAILED_FROZEN_ROOT}}" = $R26FailedFrozenRoot
        "{{R26A1_FAILED_FROZEN_ROOT}}" = $R26A1FailedFrozenRoot
        "{{COVERAGE_ATTRIBUTION_ROOT}}" = $CoverageAttributionRoot
        "{{AGENT_RUNTIME_ROOT}}" = $AgentRuntimeRoot
        "{{AGENT_SCRATCH_ROOT}}" = $AgentScratchRoot
        "{{AGENT_FROZEN_ROOT}}" = $AgentFrozenRoot
        "{{AGENT_ARCHIVE_ROOT}}" = $AgentArchiveRoot
        "{{AGENT_CACHE_ROOT}}" = $AgentCacheRoot
        "{{MAX_FOCUSED_REPAIRS}}" = [string]$MaxFocusedRepairs
    }
    foreach ($entry in $replacements.GetEnumerator()) {
        $task = $task.Replace([string]$entry.Key, [string]$entry.Value)
    }
    [System.IO.File]::WriteAllText(
        $TaskPath,
        $task,
        [System.Text.UTF8Encoding]::new($false)
    )

    Write-Section "Launch local Codex R26A2 / final R26 agent"

    $helpText = (& $codex.Source --help 2>&1 | Out-String)
    if ($helpText -match "dangerously-bypass-approvals-and-sandbox") {
        $permissionArgs = "--dangerously-bypass-approvals-and-sandbox"
        $summary.CODEX_PERMISSION_MODE = "DANGEROUSLY_BYPASS_APPROVALS_AND_SANDBOX"
    } else {
        $permissionArgs = "--ask-for-approval never --sandbox danger-full-access"
        $summary.CODEX_PERMISSION_MODE = "NEVER_APPROVAL_DANGER_FULL_ACCESS"
    }

    $codexPath = [string]$codex.Source
    $commandLine = 'call "' + $codexPath + '" ' + $permissionArgs +
        ' exec --json --output-last-message "' + $FinalMessagePath + '" -' +
        ' < "' + $TaskPath + '" > "' + $EventsPath + '" 2> "' + $StderrPath + '"'
    $cmdText = "@echo off`r`nsetlocal`r`n" + $commandLine +
        "`r`nset FAST3_CODEX_EXIT=%ERRORLEVEL%`r`nexit /b %FAST3_CODEX_EXIT%`r`n"
    [System.IO.File]::WriteAllText(
        $CodexCmdPath,
        $cmdText,
        [System.Text.ASCIIEncoding]::new()
    )

    Push-Location $RepoRoot
    try {
        $process = Start-Process -FilePath "cmd.exe" `
            -ArgumentList @("/d", "/c", "`"$CodexCmdPath`"") `
            -NoNewWindow -Wait -PassThru
        $summary.CODEX_EXIT_CODE = [int]$process.ExitCode
    }
    finally {
        Pop-Location
    }

    if (Test-Path -LiteralPath $FinalMessagePath -PathType Leaf) {
        $finalText = Get-Content -LiteralPath $FinalMessagePath -Raw -Encoding UTF8
        $patterns = @(
            "(?im)^\s*FINAL_DECISION\s*=\s*`?([A-Z0-9_:\-]+)`?\s*$",
            "(?im)Final\s+decision\s*:\s*`?([A-Z0-9_:\-]+)`?"
        )
        $found = $null
        foreach ($pattern in $patterns) {
            $match = [regex]::Match($finalText, $pattern)
            if ($match.Success) {
                $found = $match.Groups[1].Value.Trim()
                break
            }
        }
        if ($null -ne $found) {
            $summary.FINAL_DECISION = $found
        } elseif ($summary.CODEX_EXIT_CODE -eq 0) {
            $summary.FINAL_DECISION = "CODEX_COMPLETED_REVIEW_FINAL_MESSAGE"
        } else {
            $summary.FINAL_DECISION = "STOP_R26A2_R26_CODEX_EXIT_$($summary.CODEX_EXIT_CODE)"
        }
    } elseif ($summary.CODEX_EXIT_CODE -eq 0) {
        $summary.FINAL_DECISION = "STOP_R26A2_R26_FINAL_MESSAGE_MISSING"
    } else {
        $summary.FINAL_DECISION = "STOP_R26A2_R26_CODEX_EXIT_$($summary.CODEX_EXIT_CODE)"
    }

    $summary.AGENT_LAUNCHER_STATUS = "CODEX_FINISHED"
}
catch {
    $failure = $_
    $summary.AGENT_LAUNCHER_STATUS = "FAILED"
    $summary.FINAL_DECISION = "STOP_R26A2_R26_AGENT_LAUNCHER_FAILED:$($_.Exception.Message)"
}
finally {
    Write-Section "FAST3 R26A2 / final R26 post-run audit"

    try {
        $CanonicalAfter = Get-TreeMetadataHash -Root $CanonicalRoot
        [System.IO.File]::WriteAllText(
            $CanonicalAfterPath,
            $CanonicalAfter,
            [System.Text.ASCIIEncoding]::new()
        )
        $summary.CANONICAL_METADATA_UNCHANGED = ($CanonicalBefore -eq $CanonicalAfter)
        if (-not $summary.CANONICAL_METADATA_UNCHANGED) {
            $summary.FINAL_DECISION = "STOP_R26A2_R26_CANONICAL_METADATA_CHANGED"
        }
    }
    catch {
        $summary.CANONICAL_METADATA_UNCHANGED = $false
        $summary.FINAL_DECISION =
            "STOP_R26A2_R26_CANONICAL_POST_SNAPSHOT_FAILED:$($_.Exception.Message)"
    }

    try {
        $LocalResultsAfter = Get-LocalResultsInventory -RepoRoot $RepoRoot
        $beforeSet = @{}
        foreach ($item in $LocalResultsBefore) {
            $beforeSet[[string]$item] = $true
        }
        $newLocal = @(
            $LocalResultsAfter |
                Where-Object { -not $beforeSet.ContainsKey([string]$_) }
        )
        $summary.NEW_LOCAL_RESULTS_WRITE_COUNT = $newLocal.Count
        if ($newLocal.Count -gt 0) {
            $summary.FINAL_DECISION = "STOP_R26A2_R26_NEW_LOCAL_RESULTS_WRITES"
        }
    }
    catch {
        $summary.NEW_LOCAL_RESULTS_WRITE_COUNT = -1
        $summary.FINAL_DECISION =
            "STOP_R26A2_R26_LOCAL_RESULTS_AUDIT_FAILED:$($_.Exception.Message)"
    }

    try {
        $summary.UNTRACKED_FILE_PRESERVATION_PASS =
            Test-UntrackedPathsPreserved -Before $UntrackedBefore -RepoRoot $RepoRoot
        if (-not $summary.UNTRACKED_FILE_PRESERVATION_PASS) {
            $summary.FINAL_DECISION =
                "STOP_R26A2_R26_PREEXISTING_UNTRACKED_PATH_MISSING"
        }
    }
    catch {
        $summary.UNTRACKED_FILE_PRESERVATION_PASS = $false
        $summary.FINAL_DECISION =
            "STOP_R26A2_R26_UNTRACKED_PRESERVATION_AUDIT_FAILED:$($_.Exception.Message)"
    }

    $summary |
        ConvertTo-Json -Depth 10 |
        Set-Content -LiteralPath $LauncherSummaryPath -Encoding UTF8

    $report = @"
# FAST3 R26A2 / final R26 Agent Launcher Report

- RUN_ID: $RunId
- AGENT_LAUNCHER_STATUS: $($summary.AGENT_LAUNCHER_STATUS)
- CODEX_PERMISSION_MODE: $($summary.CODEX_PERMISSION_MODE)
- CODEX_EXIT_CODE: $($summary.CODEX_EXIT_CODE)
- CANONICAL_METADATA_UNCHANGED: $($summary.CANONICAL_METADATA_UNCHANGED)
- NEW_LOCAL_RESULTS_WRITE_COUNT: $($summary.NEW_LOCAL_RESULTS_WRITE_COUNT)
- UNTRACKED_FILE_PRESERVATION_PASS: $($summary.UNTRACKED_FILE_PRESERVATION_PASS)
- GIT_MUTATION_COMMAND_BLOCK_ACTIVE: $($summary.GIT_MUTATION_COMMAND_BLOCK_ACTIVE)
- FINAL_DECISION: $($summary.FINAL_DECISION)

The authoritative R26A payoff-ledger and resumed R26 decisions, when produced, are
stored under their dedicated frozen research roots. This outer report audits only the
one-click local Codex process.
"@
    [System.IO.File]::WriteAllText(
        $LauncherReportPath,
        $report,
        [System.Text.UTF8Encoding]::new($false)
    )

    foreach ($path in @(
        $TaskPath,
        $EventsPath,
        $StderrPath,
        $FinalMessagePath,
        $CodexCmdPath
    )) {
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            Copy-Item -LiteralPath $path -Destination $AgentArchiveRoot -Force
        }
    }

    Write-Section "FAST3 R26A2 / final R26 agent launcher summary"
    foreach ($entry in $summary.GetEnumerator()) {
        Write-Host "$($entry.Key)=$($entry.Value)"
    }
    Write-Host "LAUNCHER_SUMMARY_PATH=$LauncherSummaryPath"
    Write-Host "LAUNCHER_REPORT_PATH=$LauncherReportPath"

    if ($null -ne $failure) {
        Write-Error $failure
    }
}

if ([string]$summary.FINAL_DECISION -like "STOP_*") {
    exit 3
}
exit 0
