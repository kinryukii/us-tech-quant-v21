param(
    [ValidateSet('test','test_plain','test_plain_02','real','train')][string]$Phase = 'test_plain_02',
    [string]$Image = 'sha256:32365682bb6776c9f4e1abe936ab92bb7100696bc89576279d1a3c3fb9379bfe'
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$here = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$joint = (Resolve-Path -LiteralPath (Join-Path $here '..\..')).Path
$parent = Split-Path -Parent $joint
$container = "joint-capacity-aware-rl-20260927-$Phase"
$commandPath = Join-Path $here ("RUNTIME_COMMAND_$Phase.json")
$inspectPath = Join-Path $here ("CONTAINER_INSPECT_$Phase.json")
$receiptPath = Join-Path $here ("CONTAINER_RECEIPT_$Phase.json")
$logPath = Join-Path $here ("CONTAINER_$Phase.log")
foreach ($p in @($commandPath,$inspectPath,$receiptPath,$logPath)) {
    if (Test-Path -LiteralPath $p) { throw "PRESERVE_EXISTING_RUN: $p" }
}
if ($env:DOCKER_HOST -or ($env:DOCKER_CONTEXT -and $env:DOCKER_CONTEXT -ne 'desktop-linux')) {
    throw 'UNAPPROVED_DOCKER_ENVIRONMENT_ENDPOINT'
}
$context = (& docker context show 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $context -ne 'desktop-linux') { throw "UNEXPECTED_DOCKER_CONTEXT: $context" }
$contextJson = & docker context inspect desktop-linux 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) { throw 'DOCKER_CONTEXT_INSPECT_FAILED' }
$endpoint = ((ConvertFrom-Json $contextJson)[0]).Endpoints.docker.Host
if ($endpoint -ne 'npipe:////./pipe/dockerDesktopLinuxEngine') { throw "NONLOCAL_DOCKER_ENDPOINT: $endpoint" }

$files = @(
    @{ source=(Join-Path $joint 'joint_neural.py'); target='/joint/joint_neural.py' },
    @{ source=(Join-Path $joint 'engine.py'); target='/joint/engine.py' },
    @{ source=(Join-Path $joint 'models\model_registry.json'); target='/joint/models/model_registry.json' },
    @{ source=(Join-Path $here 'train_capacity_rl.py'); target='/joint/followup_review/capacity_aware_rl/train_capacity_rl.py' },
    @{ source=(Join-Path $here 'test_capacity_rl.py'); target='/joint/followup_review/capacity_aware_rl/test_capacity_rl.py' },
    @{ source=(Join-Path $here 'technical_pre2026_parity.py'); target='/joint/followup_review/capacity_aware_rl/technical_pre2026_parity.py' },
    @{ source=(Join-Path $here 'synthetic_parity_check.py'); target='/joint/followup_review/capacity_aware_rl/synthetic_parity_check.py' },
    @{ source=(Join-Path $joint 'followup_review\capacity_aware_revision\nav_context_adapter.py'); target='/joint/followup_review/capacity_aware_revision/nav_context_adapter.py' },
    @{ source=(Join-Path $here 'PRE_FIT_CONTRACT.md'); target='/joint/followup_review/capacity_aware_rl/PRE_FIT_CONTRACT.md' },
    @{ source=(Join-Path $joint 'data\pre2026_joint_context.parquet'); target='/joint/data/pre2026_joint_context.parquet' },
    @{ source=(Join-Path $parent 'a2_strict_method_retrain_20260926\results\pre2026_original_price_coordinate.parquet'); target='/a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet' }
)
foreach ($m in $files) {
    if (-not (Test-Path -LiteralPath $m.source -PathType Leaf)) { throw "SOURCE_FILE_MISSING: $($m.source)" }
}
if ($Phase -eq 'train') {
    $out = Join-Path $here 'out'
    if (Test-Path -LiteralPath $out) {
        if (@(Get-ChildItem -LiteralPath $out -Force).Count -ne 0) { throw 'PRESERVE_EXISTING_CAPACITY_RL_OUTPUT' }
    } else { New-Item -ItemType Directory -Path $out | Out-Null }
}
$existing = & docker --context desktop-linux ps -a --filter "name=^/$container$" --format '{{.Names}}'
if ($LASTEXITCODE -ne 0) { throw 'CONTAINER_LIST_FAILED' }
if ((@($existing) | Out-String).Trim() -eq $container) { throw "CONTAINER_NAME_EXISTS: $container" }
$imageJson = & docker --context desktop-linux image inspect $Image
if ($LASTEXITCODE -ne 0) { throw 'FIXED_LOCAL_IMAGE_MISSING' }
$imageInfo = ConvertFrom-Json ($imageJson | Out-String)
$script = if ($Phase -eq 'test') {
    @('-B','-m','pytest','-q','/joint/followup_review/capacity_aware_rl/test_capacity_rl.py')
} elseif ($Phase -in @('test_plain','test_plain_02')) {
    @('-B','/joint/followup_review/capacity_aware_rl/synthetic_parity_check.py')
} elseif ($Phase -eq 'real') {
    @('-B','/joint/followup_review/capacity_aware_rl/technical_pre2026_parity.py')
} else {
    @('-B','/joint/followup_review/capacity_aware_rl/train_capacity_rl.py')
}
$argv = @('create','--name',$container,'--pull=never','--network','none','--read-only',
          '--cap-drop','ALL','--security-opt','no-new-privileges',
          '--user','65532:65532','--memory','2g','--pids-limit','128','--cpus','2',
          '--tmpfs','/tmp:rw,noexec,nosuid,size=64m',
          '--env','PYTHONDONTWRITEBYTECODE=1','--env','PYTHONPATH=/joint','--env','OMP_NUM_THREADS=2',
          '--env','OPENBLAS_NUM_THREADS=2','--env','MKL_NUM_THREADS=2',
          '--workdir','/joint')
foreach ($m in $files) { $argv += @('--mount',"type=bind,source=$($m.source),target=$($m.target),readonly") }
if ($Phase -eq 'train') {
    $argv += @('--mount',"type=bind,source=$out,target=/joint/followup_review/capacity_aware_rl/out")
}
$argv += @($Image,'python') + $script
@{
    batch='a2_latest_effective_joint_20260927'; phase=$Phase
    argv=@('docker','--context','desktop-linux')+$argv
    image_id=$Image; actual_image_id=$imageInfo[0].Id; endpoint=$endpoint
    inputs=@($files | ForEach-Object {
        @{source=$_.source;target=$_.target;sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $_.source).Hash.ToLowerInvariant()}
    })
    private_output=if($Phase -eq 'train'){$out}else{$null}
    boundary='No 2026 data, old model cache, host Docker socket, or parent directory mount'
} | ConvertTo-Json -Depth 9 | Set-Content -LiteralPath $commandPath -Encoding utf8
$created = & docker --context desktop-linux @argv 2>&1
$createCode = $LASTEXITCODE
if ($createCode -ne 0) {
    @{phase='create';exit_code=$createCode;output=@($created)} | ConvertTo-Json -Depth 5 |
        Set-Content -LiteralPath $receiptPath -Encoding utf8
    throw "CAPACITY_RL_CONTAINER_CREATE_FAILED: $createCode $created"
}
$id = (@($created) | Select-Object -Last 1).ToString().Trim()
& docker --context desktop-linux inspect $id | Set-Content -LiteralPath $inspectPath -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw 'CONTAINER_INSPECT_FAILED' }
Write-Output "CAPACITY_RL_CONTAINER_CREATED $id"
$started = & docker --context desktop-linux start $id 2>&1
$startCode = $LASTEXITCODE
if ($startCode -ne 0) { throw "CONTAINER_START_FAILED: $startCode $started" }
Write-Output "CAPACITY_RL_CONTAINER_STARTED $id"
$waited = & docker --context desktop-linux wait $id 2>&1
$waitCode = $LASTEXITCODE
$exitCode = if($waitCode -eq 0){[int](@($waited)|Select-Object -Last 1).ToString().Trim()}else{$null}
$savedPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& docker --context desktop-linux logs $id *>&1 | Set-Content -LiteralPath $logPath -Encoding utf8
$logCode = $LASTEXITCODE
$ErrorActionPreference = $savedPreference
& docker --context desktop-linux inspect $id | Set-Content -LiteralPath $inspectPath -Encoding utf8
$complete = if($Phase -eq 'train'){Join-Path $out 'TRAIN_RECEIPT.json'}else{$null}
@{
    phase='finished';container_id=$id;image_id=$Image;endpoint=$endpoint
    create_cli_exit_code=$createCode;start_cli_exit_code=$startCode
    wait_cli_exit_code=$waitCode;container_exit_code=$exitCode;logs_cli_exit_code=$logCode
    train_receipt_exists=if($complete){Test-Path -LiteralPath $complete -PathType Leaf}else{$null}
    train_receipt_sha256=if($complete -and (Test-Path -LiteralPath $complete -PathType Leaf)){
        (Get-FileHash -Algorithm SHA256 -LiteralPath $complete).Hash.ToLowerInvariant()
    }else{$null}
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receiptPath -Encoding utf8
Write-Output "CAPACITY_RL_CONTAINER_EXIT $exitCode"
if($waitCode -ne 0 -or $exitCode -ne 0 -or ($Phase -eq 'train' -and -not (Test-Path -LiteralPath $complete -PathType Leaf))){
    throw 'CAPACITY_RL_RUN_FAILED_PRESERVE_CONTAINER_AND_OUTPUT'
}
