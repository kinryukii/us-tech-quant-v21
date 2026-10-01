param()

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$RunRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$R1Root = (Resolve-Path -LiteralPath (Join-Path $RunRoot '..')).Path
$SourceRoot = (Resolve-Path -LiteralPath (Join-Path $RunRoot 'source')).Path
$OutputRoot = (Resolve-Path -LiteralPath (Join-Path $RunRoot 'out')).Path
$LogsRoot = (Resolve-Path -LiteralPath (Join-Path $RunRoot 'logs')).Path
$WorkerRoot = (Resolve-Path -LiteralPath (Join-Path $R1Root 'test_handoff')).Path
$DecisionBundle = (Resolve-Path -LiteralPath (Join-Path $WorkerRoot 'decision_bundle')).Path
$ExecutionBundle = (Resolve-Path -LiteralPath (Join-Path $R1Root 'restricted_run_20260926_01/run')).Path
$Prep = Get-Content -LiteralPath (Join-Path $RunRoot 'PREP_RECEIPT.json') -Raw | ConvertFrom-Json
$ManifestPath = Join-Path $OutputRoot 'SYNTHETIC_FROZEN_TEST_BATCH.json'
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$ManifestSha = (Get-FileHash -LiteralPath $ManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
$TracePath = Join-Path $LogsRoot 'COMMANDS.jsonl'
$Image = [string]$Manifest.runtime_image_id
$IpcName = [string]$Manifest.runtime.approved_ipc_name
$IdentitySha = [string]$Manifest.decision_bundle_identity_sha256
$Utf8 = [System.Text.UTF8Encoding]::new($false)

if ($Prep.status -ne 'SYNTHETIC_ONLY_NO_REAL_MARKET_SOURCE' -or
    $Manifest.synthetic_only -ne $true -or $Manifest.not_an_approved_r1_test_source -ne $true -or
    $ManifestSha -ne [string]$Prep.manifest_sha256 -or
    $Manifest.test_source.mount_source -ne $SourceRoot -or
    $Manifest.approved_out_source -ne $OutputRoot -or
    (Test-Path -LiteralPath $TracePath)) {
    throw 'SYNTHETIC_E2E_PREFLIGHT_FAILED_OR_ALREADY_STARTED'
}

function Write-Utf8([string]$Path, [string]$Value) {
    [System.IO.File]::WriteAllText($Path, $Value, $Utf8)
}

function Write-Json([string]$Path, $Value) {
    if (Test-Path -LiteralPath $Path) { throw "EVIDENCE_ALREADY_EXISTS:$Path" }
    Write-Utf8 $Path (($Value | ConvertTo-Json -Depth 32) + "`n")
}

function Invoke-Docker([string]$Phase, [string[]]$DockerArgv) {
    $Lines = @(& docker @DockerArgv 2>&1 | ForEach-Object { [string]$_ })
    $Code = $LASTEXITCODE
    $Output = ($Lines -join "`n").Trim()
    $Record = [ordered]@{
        utc = [DateTime]::UtcNow.ToString('o')
        phase = $Phase
        argv = @('docker') + $DockerArgv
        cli_exit_code = $Code
        output = $Output
    }
    [System.IO.File]::AppendAllText($TracePath, (($Record | ConvertTo-Json -Compress -Depth 16) + "`n"), $Utf8)
    if ($Code -ne 0) { throw "DOCKER_COMMAND_FAILED:${Phase}:${Code}:${Output}" }
    return $Output
}

function Save-Inspect([string]$Phase, [string]$ContainerId, [string]$Path) {
    $Json = Invoke-Docker $Phase @('inspect', '--format', '{{json .}}', $ContainerId)
    Write-Utf8 $Path ($Json + "`n")
}

function Wait-Ready([string]$ContainerId, [string]$Phase) {
    for ($Try = 0; $Try -lt 100; $Try++) {
        & docker exec $ContainerId /bin/sh -c 'test -S /ipc/decision.sock' 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            [System.IO.File]::AppendAllText($TracePath,
                (([ordered]@{utc=[DateTime]::UtcNow.ToString('o'); phase=$Phase;
                    argv=@('docker','exec',$ContainerId,'/bin/sh','-c','test -S /ipc/decision.sock');
                    cli_exit_code=0; readiness_attempts=$Try + 1} | ConvertTo-Json -Compress -Depth 8) + "`n"), $Utf8)
            return
        }
        Start-Sleep -Milliseconds 250
    }
    throw "DECISION_SOCKET_NOT_READY:${Phase}:${ContainerId}"
}

function Container-Exit([string]$Phase, [string]$ContainerId) {
    $Text = Invoke-Docker $Phase @('wait', $ContainerId)
    return [int]($Text -split '\s+')[0]
}

function Save-CompletedContainer([string]$Key, [string]$Role, [string]$ContainerId) {
    $Log = Invoke-Docker "$Key-$Role-logs" @('logs', $ContainerId)
    Write-Utf8 (Join-Path $LogsRoot "$Key-$Role.log") ($Log + "`n")
    Save-Inspect "$Key-$Role-final-inspect" $ContainerId (Join-Path $LogsRoot "$Key-$Role-final-inspect.json")
}

$Common = @('create', '--pull=never', '--network', 'none', '--read-only',
    '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
    '--memory', '2g', '--pids-limit', '256', '--cpus', '2',
    '--user', '65532:65532', '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m')
$DecisionMounts = @('--mount', "type=bind,source=$DecisionBundle,target=/bundle,readonly",
    '--mount', "type=bind,source=$WorkerRoot,target=/worker,readonly",
    '--mount', "type=volume,source=$IpcName,target=/ipc")
$ExecutionMounts = @('--mount', "type=bind,source=$ExecutionBundle,target=/bundle,readonly",
    '--mount', "type=bind,source=$WorkerRoot,target=/worker,readonly",
    '--mount', "type=bind,source=$SourceRoot,target=/test,readonly",
    '--mount', "type=bind,source=$OutputRoot,target=/out",
    '--mount', "type=volume,source=$IpcName,target=/ipc")

function Run-Paired([string]$Key, [string]$Phase, [string]$Candidate) {
    $Mode = if ($Phase -eq 'predict') { 'predict' } else { 'target' }
    $DecisionInspect = "/out/$Key-decision-inspect.json"
    $ExecutionInspect = "/out/$Key-execution-inspect.json"
    $DecisionCmd = @('/usr/local/bin/python', '-B', '/worker/decision_service.py',
        '--mode', $Mode, '--identity-sha', $IdentitySha)
    if ($Phase -eq 'account') { $DecisionCmd += @('--candidate', $Candidate) }
    $ExecutionCmd = @('/usr/local/bin/python', '-B', '/worker/test_worker.py', $Phase,
        '--manifest', '/out/SYNTHETIC_FROZEN_TEST_BATCH.json',
        '--manifest-sha256', $ManifestSha, '--out', '/out/submission',
        '--decision-socket', '/ipc/decision.sock',
        '--decision-inspect', $DecisionInspect, '--execution-inspect', $ExecutionInspect)
    if ($Phase -eq 'account') { $ExecutionCmd += @('--candidate', $Candidate) }
    $DecisionName = "r1-se2e-d-$Key"
    $ExecutionName = "r1-se2e-x-$Key"
    $DecisionId = Invoke-Docker "$Key-decision-create" ($Common + @('--name', $DecisionName) +
        $DecisionMounts + @('--env', 'PYTHONDONTWRITEBYTECODE=1',
                           '--env', 'R1_VERIFIED_ISOLATION=1', $Image) + $DecisionCmd)
    $ExecutionId = Invoke-Docker "$Key-execution-create" ($Common + @('--name', $ExecutionName) +
        $ExecutionMounts + @('--env', 'PYTHONDONTWRITEBYTECODE=1',
                            '--env', 'R1_TRAINED_ROOT=/bundle', $Image) + $ExecutionCmd)
    Save-Inspect "$Key-decision-prestart-inspect" $DecisionId (Join-Path $OutputRoot "$Key-decision-inspect.json")
    Save-Inspect "$Key-execution-prestart-inspect" $ExecutionId (Join-Path $OutputRoot "$Key-execution-inspect.json")
    [void](Invoke-Docker "$Key-decision-start" @('start', $DecisionId))
    Wait-Ready $DecisionId $Key
    [void](Invoke-Docker "$Key-execution-start" @('start', $ExecutionId))
    $ExecutionExit = Container-Exit "$Key-execution-wait" $ExecutionId
    if ($ExecutionExit -ne 0) {
        [void](Invoke-Docker "$Key-decision-stop-after-execution-failure" @('stop', $DecisionId))
    }
    $DecisionExit = Container-Exit "$Key-decision-wait" $DecisionId
    Save-CompletedContainer $Key 'decision' $DecisionId
    Save-CompletedContainer $Key 'execution' $ExecutionId
    Write-Json (Join-Path $LogsRoot "$Key-receipt.json") ([ordered]@{
        status = if ($ExecutionExit -eq 0 -and $DecisionExit -eq 0) { 'PASS' } else { 'FAIL' }
        phase = $Phase
        candidate = $Candidate
        decision_container_id = $DecisionId
        decision_exit_code = $DecisionExit
        execution_container_id = $ExecutionId
        execution_exit_code = $ExecutionExit
        decision_inspect_sha256 = (Get-FileHash -LiteralPath (Join-Path $OutputRoot "$Key-decision-inspect.json") -Algorithm SHA256).Hash.ToLowerInvariant()
        execution_inspect_sha256 = (Get-FileHash -LiteralPath (Join-Path $OutputRoot "$Key-execution-inspect.json") -Algorithm SHA256).Hash.ToLowerInvariant()
    })
    if ($ExecutionExit -ne 0 -or $DecisionExit -ne 0) { throw "PAIRED_PHASE_FAILED:$Key" }
    [void](Invoke-Docker "$Key-decision-remove" @('rm', $DecisionId))
    [void](Invoke-Docker "$Key-execution-remove" @('rm', $ExecutionId))
    Write-Output "PASS $Key decision=$DecisionExit execution=$ExecutionExit"
}

function Run-ExecutionOnly([string]$Phase, [string]$SubmissionSha) {
    $Key = $Phase
    $Command = @('/usr/local/bin/python', '-B', '/worker/test_worker.py', $Phase,
        '--manifest', '/out/SYNTHETIC_FROZEN_TEST_BATCH.json',
        '--manifest-sha256', $ManifestSha, '--out', '/out/submission')
    if ($Phase -eq 'report') { $Command += @('--submission-seal-sha256', $SubmissionSha) }
    $ContainerId = Invoke-Docker "$Key-create" ($Common + @('--name', "r1-se2e-x-$Key") +
        $ExecutionMounts + @('--env', 'PYTHONDONTWRITEBYTECODE=1',
                            '--env', 'R1_TRAINED_ROOT=/bundle', $Image) + $Command)
    Save-Inspect "$Key-prestart-inspect" $ContainerId (Join-Path $OutputRoot "$Key-execution-inspect.json")
    [void](Invoke-Docker "$Key-start" @('start', $ContainerId))
    $ExitCode = Container-Exit "$Key-wait" $ContainerId
    Save-CompletedContainer $Key 'execution' $ContainerId
    Write-Json (Join-Path $LogsRoot "$Key-receipt.json") ([ordered]@{
        status = if ($ExitCode -eq 0) { 'PASS' } else { 'FAIL' }
        phase = $Phase
        execution_container_id = $ContainerId
        execution_exit_code = $ExitCode
        execution_inspect_sha256 = (Get-FileHash -LiteralPath (Join-Path $OutputRoot "$Key-execution-inspect.json") -Algorithm SHA256).Hash.ToLowerInvariant()
    })
    if ($ExitCode -ne 0) { throw "EXECUTION_PHASE_FAILED:$Key" }
    [void](Invoke-Docker "$Key-remove" @('rm', $ContainerId))
    Write-Output "PASS $Key execution=$ExitCode"
}

[void](Invoke-Docker 'ipc-volume-inspect' @('volume', 'inspect', $IpcName))
Run-Paired 'predict' 'predict' ''
for ($Index = 0; $Index -lt $Manifest.roster.Count; $Index++) {
    Run-Paired ("account_{0:d2}" -f ($Index + 1)) 'account' ([string]$Manifest.roster[$Index])
}
Run-ExecutionOnly 'seal' ''
$SubmissionSealPath = Join-Path $OutputRoot 'submission/SUBMISSION_SEAL.json'
$SubmissionSha = (Get-FileHash -LiteralPath $SubmissionSealPath -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Utf8 (Join-Path $LogsRoot 'SUBMISSION_SEAL_SHA256.txt') ($SubmissionSha + "`n")
Run-ExecutionOnly 'report' $SubmissionSha

$Artifacts = @(Get-ChildItem -LiteralPath (Join-Path $OutputRoot 'submission') -File | Sort-Object Name | ForEach-Object {
    [ordered]@{path=$_.Name; bytes=$_.Length; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
})
Write-Json (Join-Path $LogsRoot 'ARTIFACTS.json') ([ordered]@{synthetic_only=$true; files=$Artifacts})
Write-Json (Join-Path $RunRoot 'RUN_RECEIPT.json') ([ordered]@{
    status='SYNTHETIC_TWO_CONTAINER_E2E_PASS'
    synthetic_only=$true
    real_2026_market_read=$false
    model_fit_count=0
    rl_update_count=0
    fixed_image_id=$Image
    frozen_synthetic_manifest_sha256=$ManifestSha
    account_count=$Manifest.roster.Count
    phase_count=12
    commands_sha256=(Get-FileHash -LiteralPath $TracePath -Algorithm SHA256).Hash.ToLowerInvariant()
    artifacts_sha256=(Get-FileHash -LiteralPath (Join-Path $LogsRoot 'ARTIFACTS.json') -Algorithm SHA256).Hash.ToLowerInvariant()
    submission_seal_sha256=$SubmissionSha
    report_sha256=(Get-FileHash -LiteralPath (Join-Path $OutputRoot 'submission/TEST_REPORT.json') -Algorithm SHA256).Hash.ToLowerInvariant()
})
Write-Output 'SYNTHETIC_TWO_CONTAINER_E2E_PASS'
