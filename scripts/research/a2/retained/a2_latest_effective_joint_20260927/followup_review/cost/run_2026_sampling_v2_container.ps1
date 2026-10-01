param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('technical','run')]
    [string]$Phase,
    [ValidateSet('r6_v2_10','r6_v2_5','r6_v2_25','r7_original_10','r7_v2_10')]
    [string]$Scenario,
    [ValidateRange(1,99)]
    [int]$TechnicalAttempt = 2
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$here = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$joint = (Resolve-Path -LiteralPath (Join-Path $here '..\..')).Path
$image = 'sha256:32365682bb6776c9f4e1abe936ab92bb7100696bc89576279d1a3c3fb9379bfe'
$batch = Join-Path $joint 'evaluation_2026_sampling_v2'
if ($Phase -eq 'run' -and -not $Scenario) { throw 'SCENARIO_REQUIRED' }
if ($Phase -eq 'technical' -and $Scenario) { throw 'TECHNICAL_HAS_NO_SCENARIO' }

if ($Phase -eq 'technical') {
    $suffix = '{0:d2}' -f $TechnicalAttempt
    $name = "joint-v2-2026-technical-20260927-$suffix"
    $evidence = Join-Path $here "technical_container_20260927_$suffix"
    $output = $evidence
    $technicalFiles = @(
        'engine.py', 'run_suite.py', 'joint_linear_tree.py', 'joint_neural.py',
        'joint_risk.py', 'risk.py', 'models/predict.py', 'models/model_registry.json',
        'joint_linear_tree_coverage_v2/bundle/v2_policy.py',
        'followup_review/valuation/price_overlay.py',
        'followup_review/cost/replay_2026_sampling_v2.py',
        'followup_review/cost/run_2026_sampling_v2_container.ps1',
        'followup_review/cost/verify_2026_runner_technical.py'
    )
    $readonlyFiles = $technicalFiles
    $readonlyDirectories = @(
        @{ source=(Join-Path $joint 'joint_linear_tree_artifacts'); target='/joint/joint_linear_tree_artifacts' },
        @{ source=(Join-Path $joint 'joint_linear_tree_coverage_v2\out'); target='/joint/joint_linear_tree_coverage_v2/out' },
        @{ source=(Join-Path $joint 'joint_neural_artifacts'); target='/joint/joint_neural_artifacts' },
        @{ source=(Join-Path $joint 'risk'); target='/joint/risk' }
    )
    $entry = @('python','-B','/joint/followup_review/cost/verify_2026_runner_technical.py')
} else {
    $name = 'joint-v2-2026-' + $Scenario.Replace('_','-')
    $evidence = $batch
    $output = $batch
    $manifestPath = Join-Path $batch 'PRE_SCORE_BATCH_FREEZE.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw 'FULL_BATCH_FREEZE_MISSING' }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json -AsHashtable
    if ($manifest.status -ne 'JOINT_SAMPLING_V2_FULL_BATCH_FROZEN_BEFORE_REVISED_SCORING' -or $manifest.image_id -ne $image) {
        throw 'FULL_BATCH_FREEZE_IDENTITY_MISMATCH'
    }
    $readonlyFiles = @($manifest.runtime_files_sha256.Keys) + @($manifest.original_result_link_files_sha256.Keys)
    $readonlyFiles = @($readonlyFiles | Sort-Object -Unique)
    $readonlyDirectories = @()
    $entry = @('python','-B','/joint/followup_review/cost/replay_2026_sampling_v2.py',
               '--run',$Scenario)
}
if (-not (Test-Path -LiteralPath $output)) {
    New-Item -ItemType Directory -Path $output | Out-Null
}
$tag = if ($Phase -eq 'technical') { 'TECHNICAL' } else { $Scenario.ToUpperInvariant() }
$commandFile = Join-Path $evidence "RUNTIME_${tag}_COMMAND.json"
$inspectFile = Join-Path $evidence "RUNTIME_${tag}_INSPECT.json"
$logFile = Join-Path $evidence "RUNTIME_${tag}.log"
$receiptFile = Join-Path $evidence "RUNTIME_${tag}_RECEIPT.json"
foreach ($path in @($commandFile,$inspectFile,$logFile,$receiptFile)) {
    if (Test-Path -LiteralPath $path) { throw "PRESERVE_EXISTING_RUNTIME_EVIDENCE: $path" }
}
$existing = & docker container inspect $name 2>$null
if ($LASTEXITCODE -eq 0) { throw "CONTAINER_NAME_EXISTS: $name" }
$actualImage = (& docker image inspect --format '{{.Id}}' $image 2>&1 | Select-Object -Last 1).ToString().Trim()
if ($LASTEXITCODE -ne 0 -or $actualImage -ne $image) { throw 'FIXED_IMAGE_NOT_AVAILABLE' }

$arguments = @(
    'create','--name',$name,'--pull=never','--network','none',
    '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
    '--user','65532:65532','--memory','2g','--pids-limit','128','--cpus','2',
    '--tmpfs','/tmp:rw,noexec,nosuid,size=64m',
    '--env','PYTHONDONTWRITEBYTECODE=1',
    '--env','OMP_NUM_THREADS=2','--env','OPENBLAS_NUM_THREADS=2',
    '--env','MKL_NUM_THREADS=2','--workdir','/joint'
)
if ($Phase -eq 'technical') { $arguments += @('--env','TECH_OUTPUT_ROOT=/out') }
$mountRecord = @()
foreach ($relative in $readonlyFiles) {
    $linux = $relative.Replace('\','/')
    $source = Join-Path $joint $linux.Replace('/','\')
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "MOUNT_SOURCE_MISSING: $source" }
    $destination = "/joint/$linux"
    $arguments += @('--mount',"type=bind,source=$source,target=$destination,readonly")
    $mountRecord += @{ source=$source; target=$destination; readonly=$true }
}
foreach ($directory in $readonlyDirectories) {
    if (-not (Test-Path -LiteralPath $directory.source -PathType Container)) {
        throw "MOUNT_DIRECTORY_MISSING: $($directory.source)"
    }
    $arguments += @('--mount',"type=bind,source=$($directory.source),target=$($directory.target),readonly")
    $mountRecord += @{ source=$directory.source; target=$directory.target; readonly=$true }
}
$outputTarget = if ($Phase -eq 'technical') { '/out' } else { '/joint/evaluation_2026_sampling_v2' }
$arguments += @('--mount',"type=bind,source=$output,target=$outputTarget",$image)
$arguments += $entry
@{
    phase=$Phase; scenario=$Scenario; docker_argv=@('docker')+$arguments
    image_id=$image; mounts=$mountRecord
    writable_output=@{ source=$output; target=$outputTarget }
    no_network=$true; read_only_root=$true; memory_bytes=2147483648; pids_limit=128
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $commandFile -Encoding utf8

$created = & docker @arguments 2>&1
$createCode = $LASTEXITCODE
if ($createCode -ne 0) {
    @{ phase='create_failed'; cli_exit_code=$createCode; output=@($created) } |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receiptFile -Encoding utf8
    throw "DOCKER_CREATE_FAILED: $createCode $created"
}
$id = (@($created) | Select-Object -Last 1).ToString().Trim()
$actualInspect = & docker inspect $id
if ($LASTEXITCODE -ne 0) { throw 'DOCKER_INSPECT_FAILED' }
$actualInspect | Set-Content -LiteralPath $inspectFile -Encoding utf8
Write-Output "CONTAINER_CREATED $Phase $Scenario $id"
$started = & docker start $id 2>&1
$startCode = $LASTEXITCODE
if ($startCode -ne 0) { throw "DOCKER_START_FAILED: $startCode $started" }
Write-Output "CONTAINER_STARTED $Phase $Scenario $id"

$peakBytes = [double]0
$samples = 0
do {
    $running = (& docker inspect --format '{{.State.Running}}' $id).ToString().Trim()
    if ($running -eq 'true') {
        $usage = (& docker stats --no-stream --format '{{.MemUsage}}' $id 2>$null | Select-Object -Last 1).ToString().Trim()
        if ($usage -match '^([0-9.]+)([KMGT]i?B)') {
            $factor = switch ($Matches[2]) {
                'KiB' { 1024 } 'MiB' { 1048576 } 'GiB' { 1073741824 }
                'KB' { 1000 } 'MB' { 1000000 } 'GB' { 1000000000 }
                default { 1 }
            }
            $bytes = [double]$Matches[1] * [double]$factor
            $peakBytes = [Math]::Max($peakBytes,$bytes)
            $samples++
        }
        Start-Sleep -Seconds 2
    }
} while ($running -eq 'true')
$waited = & docker wait $id 2>&1
$waitCode = $LASTEXITCODE
$containerExit = if ($waitCode -eq 0) { [int](@($waited) | Select-Object -Last 1).ToString().Trim() } else { $null }
& docker logs $id *>&1 | Set-Content -LiteralPath $logFile -Encoding utf8
$logsCode = $LASTEXITCODE
$finalInspect = & docker inspect $id
$finalInspect | Set-Content -LiteralPath $inspectFile -Encoding utf8
$record = @{
    phase=$Phase; scenario=$Scenario; image_id=$image; container_id=$id
    create_cli_exit_code=$createCode; start_cli_exit_code=$startCode
    wait_cli_exit_code=$waitCode; container_exit_code=$containerExit
    logs_cli_exit_code=$logsCode; observed_peak_memory_bytes=[long]$peakBytes
    memory_sample_count=$samples; output_directory=$output
    complete_exists=if ($Phase -eq 'technical') {
        Test-Path -LiteralPath (Join-Path $output 'V2_2026_RUNNER_TECHNICAL_CHECK.json') -PathType Leaf
    } else {
        $spec = $manifest.scenario_plan[$Scenario]
        $path = Join-Path (Join-Path $batch $spec.folder) ('cost_' + $spec.cost)
        Test-Path -LiteralPath (Join-Path $path 'COMPLETE.json') -PathType Leaf
    }
}
$record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receiptFile -Encoding utf8
Write-Output "CONTAINER_EXIT $Phase $Scenario $containerExit PEAK_BYTES $([long]$peakBytes)"
if ($waitCode -ne 0 -or $containerExit -ne 0 -or -not $record.complete_exists) {
    throw 'CONTAINER_FAILED_PRESERVE_ALL_EVIDENCE'
}
