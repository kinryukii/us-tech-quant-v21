[CmdletBinding()]
param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$DataRoot = "D:\us-tech-quant-data",
    [string]$ResultsRoot = "D:\us-tech-quant-results",
    [string]$CacheRoot = "D:\us-tech-quant-cache",
    [string]$OldR3SourceRoot = "D:\us-tech-quant-results\fast3\agent_runs\event_factor_cohort_r3\20260802_211307",
    [string]$OldR3AuditRoot = "D:\us-tech-quant-results\fast3\agent_runs\r3_economic_integrity_audit\20260802_225457",
    [string]$PackageRoot,
    [switch]$ProbeOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Section([string]$Title) {
    Write-Host ""
    Write-Host ("=" * 80)
    Write-Host " $Title"
    Write-Host ("=" * 80)
}

function Assert-Path([string]$Path, [string]$Code, [switch]$Leaf) {
    $ok = if ($Leaf) { Test-Path -LiteralPath $Path -PathType Leaf } else { Test-Path -LiteralPath $Path }
    if (-not $ok) { throw "$Code`:$Path" }
}

if ([string]::IsNullOrWhiteSpace($PackageRoot)) {
    $PackageRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath)))
}
$PackageRoot = [System.IO.Path]::GetFullPath($PackageRoot)
$RepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)
$DataRoot = [System.IO.Path]::GetFullPath($DataRoot)
$ResultsRoot = [System.IO.Path]::GetFullPath($ResultsRoot)
$CacheRoot = [System.IO.Path]::GetFullPath($CacheRoot)
$OldR3SourceRoot = [System.IO.Path]::GetFullPath($OldR3SourceRoot)
$OldR3AuditRoot = [System.IO.Path]::GetFullPath($OldR3AuditRoot)

$RunId = Get-Date -Format "yyyyMMdd_HHmmss"
$CanonicalRoot = Join-Path $DataRoot "fast3\moomoo_24h_1m\canonical"
$AgentRunRoot = Join-Path $ResultsRoot "fast3\agent_runs\r3_coverage_rebuild_r24_resume_r1\$RunId"
$AgentCacheRoot = Join-Path $CacheRoot "fast3\r3_coverage_rebuild_r24_resume_r1\$RunId"
$ProbePath = Join-Path $PackageRoot "tools\probe_canonical_windows.py"
$TaskTemplatePath = Join-Path $PackageRoot "config\FAST3_R3_COVERAGE_REBUILD_R24_RESUME_R1_TASK.md"
$CoverageJson = Join-Path $AgentRunRoot "canonical_target_window_coverage.json"
$TaskPath = Join-Path $AgentRunRoot "CODEX_TASK.md"
$EventsPath = Join-Path $AgentRunRoot "codex_events.jsonl"
$StderrPath = Join-Path $AgentRunRoot "codex_stderr.log"
$FinalMessagePath = Join-Path $AgentRunRoot "codex_final_message.md"
$LauncherSummaryPath = Join-Path $AgentRunRoot "launcher_summary.json"

New-Item -ItemType Directory -Force -Path $AgentRunRoot, $AgentCacheRoot | Out-Null

$summary = [ordered]@{
    RUN_ID = $RunId
    FINAL_DECISION = "STOP_NOT_STARTED"
    CANONICAL_COVERAGE_PROBE_EXIT_CODE = $null
    CODEX_EXIT_CODE = $null
    RAW_DATA_SUFFICIENT = $false
    R3_REBUILD_PERFORMED = $false
    R24_RERUN_PERFORMED = $false
    CANONICAL_WRITE_COUNT = 0
    OLD_R3_FROZEN_OUTPUT_MUTATION_COUNT = 0
    NEW_LOCAL_RESULTS_WRITE_COUNT = 0
    GIT_COMMAND_PERFORMED = $false
    AGENT_RUN_ROOT = $AgentRunRoot
    COVERAGE_REPORT = $CoverageJson
    FINAL_MESSAGE_PATH = $FinalMessagePath
}

try {
    Write-Section "FAST3 canonical target-window coverage preflight"
    Assert-Path $RepoRoot "REPO_ROOT_MISSING"
    Assert-Path $CanonicalRoot "CANONICAL_ROOT_MISSING"
    Assert-Path $OldR3SourceRoot "OLD_R3_SOURCE_ROOT_MISSING"
    Assert-Path $OldR3AuditRoot "OLD_R3_AUDIT_ROOT_MISSING"
    Assert-Path $ProbePath "PROBE_SCRIPT_MISSING" -Leaf
    Assert-Path $TaskTemplatePath "TASK_TEMPLATE_MISSING" -Leaf

    $Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $PythonCommand) { throw "PYTHON_NOT_FOUND" }
        $Python = $PythonCommand.Source
    }

    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONPYCACHEPREFIX = Join-Path $AgentCacheRoot "pycache"
    $env:TMP = Join-Path $AgentCacheRoot "tmp"
    $env:TEMP = $env:TMP
    New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null

    & $Python $ProbePath --canonical-root $CanonicalRoot --output $CoverageJson
    $probeExit = $LASTEXITCODE
    $summary.CANONICAL_COVERAGE_PROBE_EXIT_CODE = $probeExit
    if (-not (Test-Path -LiteralPath $CoverageJson -PathType Leaf)) {
        throw "CANONICAL_COVERAGE_REPORT_MISSING"
    }
    $coverage = Get-Content -LiteralPath $CoverageJson -Raw -Encoding UTF8 | ConvertFrom-Json
    $summary.RAW_DATA_SUFFICIENT = [bool]$coverage.raw_data_sufficient_for_minimum_r24_window_occupancy
    if ($probeExit -ne 0 -or -not $summary.RAW_DATA_SUFFICIENT) {
        $summary.FINAL_DECISION = [string]$coverage.final_decision
        throw "CANONICAL_TARGET_WINDOW_GATE_FAILED:$($summary.FINAL_DECISION)"
    }

    Write-Host "RAW_DATA_SUFFICIENT=true"
    Write-Host "CANONICAL_COVERAGE_REPORT=$CoverageJson"

    if ($ProbeOnly) {
        $summary.FINAL_DECISION = "PASS_PROBE_ONLY_CANONICAL_TARGET_WINDOWS_HAVE_REAL_DATA"
        return
    }

    Write-Section "Prepare bounded R3 rebuild and R24 resume task"
    $task = Get-Content -LiteralPath $TaskTemplatePath -Raw -Encoding UTF8
    $replacements = [ordered]@{
        "{{REPO_ROOT}}" = $RepoRoot
        "{{DATA_ROOT}}" = $DataRoot
        "{{RESULTS_ROOT}}" = $ResultsRoot
        "{{CACHE_ROOT}}" = $CacheRoot
        "{{CANONICAL_ROOT}}" = $CanonicalRoot
        "{{OLD_R3_SOURCE_ROOT}}" = $OldR3SourceRoot
        "{{OLD_R3_AUDIT_ROOT}}" = $OldR3AuditRoot
        "{{COVERAGE_PROBE_JSON}}" = $CoverageJson
        "{{AGENT_RUN_ROOT}}" = $AgentRunRoot
    }
    foreach ($entry in $replacements.GetEnumerator()) {
        $task = $task.Replace([string]$entry.Key, [string]$entry.Value)
    }
    [System.IO.File]::WriteAllText($TaskPath, $task, [System.Text.UTF8Encoding]::new($false))

    $codex = Get-Command codex -ErrorAction SilentlyContinue
    if ($null -eq $codex) { throw "CODEX_CLI_NOT_FOUND_OPEN_CODEX_MANUALLY_WITH_TASK:$TaskPath" }

    Write-Section "Run one bounded Codex agent cycle"
    Push-Location $RepoRoot
    try {
        Get-Content -LiteralPath $TaskPath -Raw -Encoding UTF8 |
            & $codex.Source --ask-for-approval never exec --json --sandbox workspace-write --output-last-message $FinalMessagePath - `
                2> $StderrPath | Tee-Object -FilePath $EventsPath
        $codexExit = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    $summary.CODEX_EXIT_CODE = $codexExit

    if (Test-Path -LiteralPath $FinalMessagePath -PathType Leaf) {
        $finalText = Get-Content -LiteralPath $FinalMessagePath -Raw -Encoding UTF8
        foreach ($key in @(
            "R3_REBUILD_PERFORMED", "R24_RERUN_PERFORMED", "MODEL_FIT_STARTED",
            "MODEL_FIT_COMPLETED", "STORAGE_CONTRACT_PASS", "SUMMARY_READABLE",
            "ALL_REQUIRED_FROZEN_ARTIFACTS_PRESENT", "FINAL_DECISION"
        )) {
            $match = [regex]::Match($finalText, "(?im)^\s*" + [regex]::Escape($key) + "\s*=\s*(.+?)\s*$")
            if ($match.Success) {
                $value = $match.Groups[1].Value.Trim()
                if ($key -eq "FINAL_DECISION") { $summary.FINAL_DECISION = $value }
                elseif ($key -eq "R3_REBUILD_PERFORMED") { $summary.R3_REBUILD_PERFORMED = $value -match "^(?i:true)$" }
                elseif ($key -eq "R24_RERUN_PERFORMED") { $summary.R24_RERUN_PERFORMED = $value -match "^(?i:true)$" }
            }
        }
    }

    if ($codexExit -ne 0 -and $summary.FINAL_DECISION -eq "STOP_NOT_STARTED") {
        $summary.FINAL_DECISION = "STOP_CODEX_AGENT_EXIT_$codexExit"
    }
    elseif ($summary.FINAL_DECISION -eq "STOP_NOT_STARTED") {
        $summary.FINAL_DECISION = "CODEX_COMPLETED_REVIEW_FINAL_MESSAGE"
    }
}
catch {
    if ($summary.FINAL_DECISION -eq "STOP_NOT_STARTED") {
        $summary.FINAL_DECISION = "STOP_PATCH_LAUNCHER_FAILED:$($_.Exception.Message)"
    }
    Write-Error $_
}
finally {
    $summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $LauncherSummaryPath -Encoding UTF8
    Write-Section "FAST3 R3 coverage rebuild / R24 resume launcher summary"
    foreach ($entry in $summary.GetEnumerator()) {
        Write-Host "$($entry.Key)=$($entry.Value)"
    }
    Write-Host "LAUNCHER_SUMMARY_PATH=$LauncherSummaryPath"
}

if ($summary.FINAL_DECISION -like "STOP_*") { exit 3 }
exit 0
