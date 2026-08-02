[CmdletBinding()]
param([int]$Tail = 40)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RuntimeRoot = "D:\us-tech-quant-results\fast3_autoresearch\agent_runtime"
$StatePath = Join-Path $RuntimeRoot "launcher_state.json"
$LockPath = Join-Path $RuntimeRoot "FAST3_AGENT.lock"

Write-Host "FAST3 AI AGENT STATUS"
Write-Host "====================="

if (-not (Test-Path -LiteralPath $RuntimeRoot)) {
    Write-Host "Runtime directory does not exist:"
    Write-Host "  $RuntimeRoot"
    exit 0
}

if (Test-Path -LiteralPath $LockPath) {
    $pidText = (Get-Content -LiteralPath $LockPath -Raw).Trim()
    $process = $null
    if ($pidText -match '^\d+$') {
        $process = Get-Process -Id ([int]$pidText) -ErrorAction SilentlyContinue
    }
    if ($null -ne $process) {
        Write-Host "RUNNING=True"
        Write-Host "PID=$pidText"
        Write-Host "START_TIME=$($process.StartTime)"
        Write-Host "CPU_SECONDS=$($process.CPU)"
    }
    else {
        Write-Host "RUNNING=False"
        Write-Host "STALE_LOCK_PID=$pidText"
    }
}
else {
    Write-Host "RUNNING=False"
}

if (Test-Path -LiteralPath $StatePath) {
    Write-Host ""
    Write-Host "Latest launcher state:"
    Get-Content -LiteralPath $StatePath
}

$latestMessage = Get-ChildItem -LiteralPath $RuntimeRoot `
    -Filter "*.last_message.md" -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if ($null -ne $latestMessage) {
    Write-Host ""
    Write-Host "Latest agent message: $($latestMessage.FullName)"
    Write-Host "------------------------------------------------------------"
    Get-Content -LiteralPath $latestMessage.FullName -Tail $Tail
}

$latestStderr = Get-ChildItem -LiteralPath $RuntimeRoot `
    -Filter "*.stderr.log" -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (($null -ne $latestStderr) -and ($latestStderr.Length -gt 0)) {
    Write-Host ""
    Write-Host "Latest stderr: $($latestStderr.FullName)"
    Write-Host "------------------------------------------------------------"
    Get-Content -LiteralPath $latestStderr.FullName -Tail $Tail
}
