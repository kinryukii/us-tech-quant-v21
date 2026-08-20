param(
    [switch]$ProspectiveAccumulate
)

$ErrorActionPreference = "Stop"
$repoRoot = "D:\us-tech-quant"
$runId = "20260810T182520Z"
$resumeState = "D:\us-tech-quant-results\frozen\fast3\overnight_factor_lab_20260810T182520Z\FAST3_OVERNIGHT_RESUME_STATE.json"
$runtimeRoot = "D:\us-tech-quant-results\runtime\fast3\overnight_factor_lab_20260810T182520Z"
$cacheRoot = "D:\us-tech-quant-cache"
$pythonRunner = Join-Path $repoRoot "fast3\scripts\run\fast3_overnight_factor_lab_r1.py"
$logPath = Join-Path $runtimeRoot "FAST3_OVERNIGHT_AUTONOMOUS_DRIVER.log"

New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $cacheRoot "pycache\overnight_factor_lab_20260810T182520Z") | Out-Null
$env:PYTHONPYCACHEPREFIX = Join-Path $cacheRoot "pycache\overnight_factor_lab_20260810T182520Z"
$env:JOBLIB_TEMP_FOLDER = Join-Path $cacheRoot "joblib\overnight_factor_lab_20260810T182520Z"
$env:TEMP = Join-Path $cacheRoot "temp\overnight_factor_lab_20260810T182520Z"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:JOBLIB_TEMP_FOLDER,$env:TEMP | Out-Null

$verifyArgs = @($pythonRunner, "--verify-only", "--run-id", $runId, "--resume-state", $resumeState)
& python @verifyArgs *>> $logPath
if ($LASTEXITCODE -ne 0) { throw "Frozen identity verification failed closed with exit code $LASTEXITCODE" }

$modeArgs = if ($ProspectiveAccumulate) {
    @($pythonRunner, "--prospective-accumulate", "--run-id", $runId, "--resume-state", $resumeState)
} else {
    @($pythonRunner, "--execute-all", "--run-id", $runId, "--resume-state", $resumeState)
}
$processRecord = [ordered]@{
    PROCESS_ID = $PID
    PROCESS_START_TIME = (Get-Process -Id $PID).StartTime.ToUniversalTime().ToString("o")
    COMMAND = "python " + (($modeArgs | ForEach-Object { '"' + $_ + '"' }) -join " ")
    LOG_PATH = $logPath
    RESUME_STATE_PATH = $resumeState
    CODEX_SESSION_REQUIRED_FOR_CONTINUATION = $false
}
$processRecord | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $runtimeRoot "AUTONOMOUS_PROCESS.json") -Encoding UTF8

& python @modeArgs *>> $logPath
$exitCode = $LASTEXITCODE
Add-Content -LiteralPath $logPath -Value ("AUTONOMOUS_DRIVER_EXIT_CODE=" + $exitCode)
exit $exitCode
