param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('freeze','run')]
    [string]$Phase,
    [ValidateSet('original','v2')]
    [string]$Scenario
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$joint = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$here = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$image = 'sha256:32365682bb6776c9f4e1abe936ab92bb7100696bc89576279d1a3c3fb9379bfe'
$out = Join-Path $here 'R9_2026_AAPL'
$evidence = Join-Path $here 'r9_aapl'
$r8FreezePath = Join-Path $here 'R8_2026_MU_T\PRE_R8_REPLAY_FREEZE.json'
if ($Phase -eq 'run' -and -not $Scenario) { throw 'R9_SCENARIO_REQUIRED' }
if ($Phase -eq 'freeze' -and $Scenario) { throw 'R9_FREEZE_HAS_NO_SCENARIO' }

$context = (& docker context show 2>&1 | Select-Object -Last 1).ToString().Trim()
if ($LASTEXITCODE -ne 0) { throw 'DOCKER_CONTEXT_QUERY_FAILED' }
$endpoint = (& docker context inspect $context --format '{{.Endpoints.docker.Host}}' 2>&1 | Select-Object -Last 1).ToString().Trim()
if ($LASTEXITCODE -ne 0 -or $endpoint -ne 'npipe:////./pipe/dockerDesktopLinuxEngine') {
    throw "ONLY_APPROVED_LOCAL_DOCKER_ENDPOINT: $endpoint"
}
$actualImage = (& docker image inspect --format '{{.Id}}' $image 2>&1 | Select-Object -Last 1).ToString().Trim()
if ($LASTEXITCODE -ne 0 -or $actualImage -ne $image) { throw 'FIXED_IMAGE_NOT_AVAILABLE' }
if (-not (Test-Path -LiteralPath $r8FreezePath -PathType Leaf)) { throw 'R8_FREEZE_MISSING' }
$r8 = Get-Content -LiteralPath $r8FreezePath -Raw | ConvertFrom-Json -AsHashtable
if ($r8.status -ne 'R8_MU_T_POLICY_INDEPENDENT_EVALUATION_REPLAY_FROZEN' -or
    $r8.image_id -ne $image) { throw 'R8_FREEZE_IDENTITY_MISMATCH' }

if ($Phase -eq 'freeze') {
    $relativeFiles = @($r8.input_files_sha256.Keys)
    $relativeFiles += @(
        'followup_review/valuation/R8_2026_MU_T/PRE_R8_REPLAY_FREEZE.json',
        'followup_review/valuation/R9_AAPL_SCOPE_BEFORE_REPLAY.md',
        'followup_review/valuation/aapl_triage/EVENT_PUBLIC_SOURCES.json',
        'followup_review/valuation/aapl_triage/TRIAGE_REPORT.md',
        'followup_review/valuation/r9_aapl/build_r9_aapl_gate.py',
        'followup_review/valuation/r9_aapl/R9_AAPL_THREE_EVENT_VERDICTS.csv',
        'followup_review/valuation/r9_aapl/R9_AAPL_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet',
        'followup_review/valuation/r9_aapl/R9_AAPL_OVERLAY_RECEIPT.json',
        'followup_review/valuation/r9_aapl/verify_r9_aapl_adapter.py',
        'followup_review/valuation/r9_aapl/R9_ADAPTER_TECHNICAL_CHECK.json',
        'followup_review/valuation/price_overlay_r9_aapl.py',
        'followup_review/valuation/replay_r9_aapl.py',
        'followup_review/valuation/run_r9_aapl_container.ps1'
    )
    $relativeFiles = @($relativeFiles | ForEach-Object { $_.Replace('\','/') } | Sort-Object -Unique)
    if (@($relativeFiles | Where-Object { $_.StartsWith('evaluation_2026/') }).Count -ne 0) {
        throw 'PRIOR_ECONOMIC_RESULT_IN_R9_MOUNT_SET'
    }
    if (Test-Path -LiteralPath $out) {
        if (@(Get-ChildItem -LiteralPath $out).Count -gt 0) { throw 'PRESERVE_EXISTING_R9_OUTPUT' }
    } else { New-Item -ItemType Directory -Path $out | Out-Null }
    $output = $out
    $outputTarget = '/joint/followup_review/valuation/R9_2026_AAPL'
    $entry = @('python','-B','/joint/followup_review/valuation/replay_r9_aapl.py','--freeze')
    $tag = 'FREEZE'
    $name = 'joint-r9-aapl-freeze-20260927'
} else {
    $freezePath = Join-Path $out 'PRE_R9_REPLAY_FREEZE.json'
    if (-not (Test-Path -LiteralPath $freezePath -PathType Leaf)) { throw 'R9_FREEZE_MISSING' }
    $r9 = Get-Content -LiteralPath $freezePath -Raw | ConvertFrom-Json -AsHashtable
    if ($r9.status -ne 'R9_AAPL_POLICY_INDEPENDENT_EVALUATION_REPLAY_FROZEN' -or
        $r9.image_id -ne $image -or $r9.prior_r8_replay_freeze_sha256 -ne
        (Get-FileHash -LiteralPath $r8FreezePath -Algorithm SHA256).Hash.ToLowerInvariant()) {
        throw 'R9_FREEZE_IDENTITY_MISMATCH'
    }
    $relativeFiles = @($r9.input_files_sha256.Keys | Sort-Object -Unique)
    if (@($relativeFiles | Where-Object { $_.StartsWith('evaluation_2026/') }).Count -ne 0) {
        throw 'PRIOR_ECONOMIC_RESULT_IN_R9_MOUNT_SET'
    }
    $output = Join-Path $out $Scenario
    if (Test-Path -LiteralPath $output) {
        if (@(Get-ChildItem -LiteralPath $output).Count -gt 0) { throw 'PRESERVE_EXISTING_R9_SCENARIO' }
    } else { New-Item -ItemType Directory -Path $output | Out-Null }
    $outputTarget = '/joint/followup_review/valuation/R9_2026_AAPL/' + $Scenario
    $entry = @('python','-B','/joint/followup_review/valuation/replay_r9_aapl.py','--run',$Scenario)
    $tag = 'RUN_' + $Scenario.ToUpperInvariant()
    $name = 'joint-r9-aapl-' + $Scenario + '-20260927'
}

if (-not (Test-Path -LiteralPath $evidence -PathType Container)) { throw 'R9_EVIDENCE_DIRECTORY_MISSING' }
$commandFile = Join-Path $evidence "RUNTIME_${tag}_COMMAND.json"
$inspectFile = Join-Path $evidence "RUNTIME_${tag}_INSPECT.json"
$logFile = Join-Path $evidence "RUNTIME_${tag}.log"
$receiptFile = Join-Path $evidence "RUNTIME_${tag}_RECEIPT.json"
foreach ($path in @($commandFile,$inspectFile,$logFile,$receiptFile)) {
    if (Test-Path -LiteralPath $path) { throw "PRESERVE_EXISTING_RUNTIME_EVIDENCE: $path" }
}
$existing = & docker container inspect $name 2>$null
if ($LASTEXITCODE -eq 0) { throw "CONTAINER_NAME_EXISTS: $name" }

$dockerArgs = @(
    'create','--name',$name,'--pull=never','--network','none',
    '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
    '--user','65532:65532','--memory','2g','--pids-limit','128','--cpus','2',
    '--tmpfs','/tmp:rw,noexec,nosuid,size=64m',
    '--env','PYTHONDONTWRITEBYTECODE=1','--env','OMP_NUM_THREADS=2',
    '--env','OPENBLAS_NUM_THREADS=2','--env','MKL_NUM_THREADS=2',
    '--workdir','/joint'
)
$mounts = @()
foreach ($relative in $relativeFiles) {
    $linux = $relative.Replace('\','/')
    $source = Join-Path $joint $linux.Replace('/','\')
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "R9_INPUT_MISSING: $source" }
    $expected = if ($Phase -eq 'freeze') {
        if ($r8.input_files_sha256.ContainsKey($linux)) { $r8.input_files_sha256[$linux] } else { $null }
    } else { $r9.input_files_sha256[$linux] }
    if ($expected) {
        $actual = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $expected) { throw "R9_INPUT_HASH_MISMATCH: $source" }
    }
    $target = '/joint/' + $linux
    $dockerArgs += @('--mount',"type=bind,source=$source,target=$target,readonly")
    $mounts += @{ source=$source; target=$target; readonly=$true }
}
if ($Phase -eq 'run') {
    $freezePath = Join-Path $out 'PRE_R9_REPLAY_FREEZE.json'
    $dockerArgs += @('--mount',"type=bind,source=$freezePath,target=/joint/followup_review/valuation/R9_2026_AAPL/PRE_R9_REPLAY_FREEZE.json,readonly")
    $mounts += @{ source=$freezePath; target='/joint/followup_review/valuation/R9_2026_AAPL/PRE_R9_REPLAY_FREEZE.json'; readonly=$true }
}
$dockerArgs += @('--mount',"type=bind,source=$output,target=$outputTarget",$image)
$dockerArgs += $entry
@{
    phase=$Phase; scenario=$Scenario; docker_argv=@('docker')+$dockerArgs
    endpoint=$endpoint; image_id=$image; mounts=$mounts
    writable_output=@{ source=$output; target=$outputTarget }
    no_network=$true; read_only_root=$true; memory_bytes=2147483648
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $commandFile -Encoding utf8

$created = & docker @dockerArgs 2>&1
$createCode = $LASTEXITCODE
if ($createCode -ne 0) {
    @{ status='CREATE_FAILED'; exit_code=$createCode; output=@($created) } |
        ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $receiptFile -Encoding utf8
    throw "R9_DOCKER_CREATE_FAILED: $createCode $created"
}
$id = (@($created) | Select-Object -Last 1).ToString().Trim()
$initial = & docker inspect $id
if ($LASTEXITCODE -ne 0) { throw 'R9_DOCKER_INSPECT_FAILED' }
$initial | Set-Content -LiteralPath $inspectFile -Encoding utf8
Write-Output "R9_CONTAINER_CREATED $Phase $Scenario $id"
$started = & docker start $id 2>&1
$startCode = $LASTEXITCODE
if ($startCode -ne 0) { throw "R9_DOCKER_START_FAILED: $startCode $started" }

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
            $peakBytes = [Math]::Max($peakBytes,[double]$Matches[1]*[double]$factor)
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
(& docker inspect $id) | Set-Content -LiteralPath $inspectFile -Encoding utf8
$complete = if ($Phase -eq 'freeze') {
    Test-Path -LiteralPath (Join-Path $out 'PRE_R9_REPLAY_FREEZE.json') -PathType Leaf
} else {
    Test-Path -LiteralPath (Join-Path $output 'COMPLETE.json') -PathType Leaf
}
@{
    phase=$Phase; scenario=$Scenario; endpoint=$endpoint; image_id=$image
    container_id=$id; create_cli_exit_code=$createCode; start_cli_exit_code=$startCode
    wait_cli_exit_code=$waitCode; container_exit_code=$containerExit
    logs_cli_exit_code=$logsCode; observed_peak_memory_bytes=[long]$peakBytes
    memory_sample_count=$samples; complete_exists=$complete
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receiptFile -Encoding utf8
Write-Output "R9_CONTAINER_EXIT $Phase $Scenario $containerExit PEAK_BYTES $([long]$peakBytes)"
if ($waitCode -ne 0 -or $containerExit -ne 0 -or -not $complete) {
    throw 'R9_CONTAINER_FAILED_PRESERVE_EVIDENCE'
}
