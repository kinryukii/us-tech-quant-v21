[CmdletBinding()]
param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [int]$MorningHour = 9,
    [int]$MaxResumeCycles = 12
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

Set-Location -LiteralPath $RepoRoot

$promptPath = Join-Path $RepoRoot "fast3\docs\legacy\prompts\archive\CODEX_FAST3_OVERNIGHT_PROMPT.txt"
$root = Join-Path $RepoRoot "..\us-tech-quant-results\fast3\archive\legacy_v22\FAST3_OVERNIGHT_AUTOPILOT"
$doneFlag = Join-Path $root "OVERNIGHT_DONE.flag"
$logDir = Join-Path $root "codex_logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$deadline = (Get-Date).Date.AddHours($MorningHour)
if ($deadline -le (Get-Date)) {
    $deadline = $deadline.AddDays(1)
}

Write-Host "FAST3_OVERNIGHT_START=$(Get-Date -Format o)"
Write-Host "DEADLINE=$($deadline.ToString('o'))"
Write-Host "MAX_RESUME_CYCLES=$MaxResumeCycles"
Write-Host "DONE_FLAG=$doneFlag"

$initialLog = Join-Path $logDir ("initial_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")
Get-Content -LiteralPath $promptPath -Raw -Encoding UTF8 |
    codex exec - 2>&1 |
    Tee-Object -FilePath $initialLog
$initialExit = $LASTEXITCODE

Write-Host "INITIAL_CODEX_EXIT=$initialExit"

$cycle = 0
while (
    -not (Test-Path -LiteralPath $doneFlag) -and
    (Get-Date) -lt $deadline -and
    $cycle -lt $MaxResumeCycles
) {
    $cycle++
    Start-Sleep -Seconds 30

    $followUp = @"
Resume the same FAST3 overnight objective from CODEX_STATUS.md and CODEX_PLAN.md.
Inspect work completed by the previous turn. Continue from the first incomplete
high-value checkpoint. Do not repeat completed experiments. Repair failures, run the
next required validation or random as-of robustness experiment, and update the
experiment ledger. End only at a defined stop condition. Create OVERNIGHT_DONE.flag
only after the final overnight package is complete. Resume cycle: $cycle.
"@

    $cycleLog = Join-Path $logDir ("resume_{0:D2}_{1}.log" -f $cycle, (Get-Date -Format "yyyyMMdd_HHmmss"))
    codex exec resume --last $followUp 2>&1 |
        Tee-Object -FilePath $cycleLog
    $exitCode = $LASTEXITCODE
    Write-Host "RESUME_CYCLE=$cycle EXIT_CODE=$exitCode"

    $combined = Get-Content -LiteralPath $cycleLog -Raw -ErrorAction SilentlyContinue
    if (
        $exitCode -ne 0 -and
        $combined -match '(?i)usage limit|rate limit|quota|credits exhausted|weekly limit'
    ) {
        Write-Host "STOP_REASON=CODEX_USAGE_OR_RATE_LIMIT"
        break
    }

    if ($exitCode -ne 0) {
        Start-Sleep -Seconds 90
    }
}

$endReason = "DEADLINE_OR_CYCLE_LIMIT"
if (Test-Path -LiteralPath $doneFlag) {
    $endReason = "OVERNIGHT_DONE_FLAG_CREATED"
} elseif ((Get-Date) -ge $deadline) {
    $endReason = "MORNING_DEADLINE_REACHED"
} elseif ($cycle -ge $MaxResumeCycles) {
    $endReason = "MAX_RESUME_CYCLES_REACHED"
}

Write-Host "FAST3_OVERNIGHT_END=$(Get-Date -Format o)"
Write-Host "END_REASON=$endReason"
Write-Host "DONE_FLAG_EXISTS=$(Test-Path -LiteralPath $doneFlag)"
Write-Host "STATUS_PATH=$(Join-Path $RepoRoot 'CODEX_STATUS.md')"
Write-Host "REPORT_PATH=$(Join-Path $root 'overnight_report.md')"
