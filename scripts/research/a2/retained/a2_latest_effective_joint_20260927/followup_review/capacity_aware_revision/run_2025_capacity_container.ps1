param(
    [ValidateSet('freeze','run')][string]$Phase,
    [string]$Image = 'sha256:32365682bb6776c9f4e1abe936ab92bb7100696bc89576279d1a3c3fb9379bfe'
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$here = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$joint = (Resolve-Path -LiteralPath (Join-Path $here '..\..')).Path
$parent = Split-Path -Parent $joint
$out = Join-Path $here 'evaluation_2025_01'
$name = "joint-capacity-2025-$Phase-01"
$commandPath = Join-Path $here ("2025_$Phase.COMMAND.json")
$inspectPath = Join-Path $here ("2025_$Phase.INSPECT.json")
$receiptPath = Join-Path $here ("2025_$Phase.RECEIPT.json")
$logPath = Join-Path $here ("2025_$Phase.LOG.txt")
foreach ($p in @($commandPath,$inspectPath,$receiptPath,$logPath)) {
    if (Test-Path -LiteralPath $p) { throw "PRESERVE_EXISTING_2025_PHASE: $p" }
}
if ($env:DOCKER_HOST -or ($env:DOCKER_CONTEXT -and $env:DOCKER_CONTEXT -ne 'desktop-linux')) {
    throw 'UNAPPROVED_DOCKER_ENDPOINT_ENVIRONMENT'
}
$context = (& docker context show 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $context -ne 'desktop-linux') { throw "UNEXPECTED_DOCKER_CONTEXT: $context" }
$contextJson = & docker context inspect desktop-linux 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) { throw 'DOCKER_CONTEXT_INSPECT_FAILED' }
$endpoint = ((ConvertFrom-Json $contextJson)[0]).Endpoints.docker.Host
if ($endpoint -ne 'npipe:////./pipe/dockerDesktopLinuxEngine') { throw "NONLOCAL_DOCKER_ENDPOINT: $endpoint" }
$imageJson = & docker --context desktop-linux image inspect $Image
if ($LASTEXITCODE -ne 0) { throw 'FIXED_LOCAL_IMAGE_MISSING' }
$actualImage = ((ConvertFrom-Json ($imageJson | Out-String))[0]).Id
if ($actualImage -ne $Image) { throw "FIXED_IMAGE_ID_MISMATCH: $actualImage" }
if ($Phase -eq 'freeze') {
    if (Test-Path -LiteralPath $out) {
        if (@(Get-ChildItem -LiteralPath $out -Force).Count -ne 0) { throw 'PRESERVE_EXISTING_2025_OUTPUT' }
    } else { New-Item -ItemType Directory -Path $out | Out-Null }
} else {
    if (-not (Test-Path -LiteralPath (Join-Path $out 'PRE_REPLAY_FREEZE.json') -PathType Leaf)) {
        throw 'MISSING_PRE_2025_FREEZE'
    }
}
$files = @(
    @{source=(Join-Path $joint 'engine.py');target='/joint/engine.py'},
    @{source=(Join-Path $joint 'joint_neural.py');target='/joint/joint_neural.py'},
    @{source=(Join-Path $joint 'joint_linear_tree.py');target='/joint/joint_linear_tree.py'},
    @{source=(Join-Path $joint 'models\model_registry.json');target='/joint/models/model_registry.json'},
    @{source=(Join-Path $joint 'data\pre2026_joint_context.parquet');target='/joint/data/pre2026_joint_context.parquet'},
    @{source=(Join-Path $joint 'evaluation_2025_sampling_v2\PRE_REPLAY_FREEZE.json');target='/joint/evaluation_2025_sampling_v2/PRE_REPLAY_FREEZE.json'},
    @{source=(Join-Path $joint 'joint_linear_tree_coverage_v2\out\FIT_RECEIPT.json');target='/joint/joint_linear_tree_coverage_v2/out/FIT_RECEIPT.json'},
    @{source=(Join-Path $joint 'joint_neural_artifacts\TRAIN_RECEIPT.json');target='/joint/joint_neural_artifacts/TRAIN_RECEIPT.json'},
    @{source=(Join-Path $joint 'evaluation_2025_sampling_v2\COMPLETE.json');target='/joint/evaluation_2025_sampling_v2/COMPLETE.json'},
    @{source=(Join-Path $joint 'evaluation_2025_sampling_v2\comparison.csv');target='/joint/evaluation_2025_sampling_v2/comparison.csv'},
    @{source=(Join-Path $joint 'evaluation_2025_sampling_v2\joint_hgb_10bps\metadata.json');target='/joint/evaluation_2025_sampling_v2/joint_hgb_10bps/metadata.json'},
    @{source=(Join-Path $joint 'evaluation_2025\COMPLETE.json');target='/joint/evaluation_2025/COMPLETE.json'},
    @{source=(Join-Path $joint 'evaluation_2025\comparison.csv');target='/joint/evaluation_2025/comparison.csv'},
    @{source=(Join-Path $joint 'evaluation_2025\joint_rl_ensemble_10bps\metadata.json');target='/joint/evaluation_2025/joint_rl_ensemble_10bps/metadata.json'},
    @{source=(Join-Path $parent 'a2_strict_method_retrain_20260926\results\pre2026_original_price_coordinate.parquet');target='/a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet'},
    @{source=(Join-Path $parent 'a2_strict_method_retrain_20260926\results\hgb\pre2026_oof.parquet');target='/a2_strict_method_retrain_20260926/results/hgb/pre2026_oof.parquet'},
    @{source=(Join-Path $here 'nav_context_adapter.py');target='/joint/followup_review/capacity_aware_revision/nav_context_adapter.py'},
    @{source=(Join-Path $here 'replay_2025_capacity.py');target='/joint/followup_review/capacity_aware_revision/replay_2025_capacity.py'},
    @{source=(Join-Path $here 'run_2025_capacity_container.ps1');target='/joint/followup_review/capacity_aware_revision/run_2025_capacity_container.ps1'},
    @{source=(Join-Path $here 'CONTRACT_BEFORE_FIT.md');target='/joint/followup_review/capacity_aware_revision/CONTRACT_BEFORE_FIT.md'},
    @{source=(Join-Path $joint 'followup_review\capacity_aware_supervised\SCIENCE_CONTRACT.md');target='/joint/followup_review/capacity_aware_supervised/SCIENCE_CONTRACT.md'},
    @{source=(Join-Path $joint 'followup_review\capacity_aware_supervised\one_step_label.py');target='/joint/followup_review/capacity_aware_supervised/one_step_label.py'},
    @{source=(Join-Path $joint 'followup_review\capacity_aware_supervised\prepare_fit.py');target='/joint/followup_review/capacity_aware_supervised/prepare_fit.py'},
    @{source=(Join-Path $joint 'followup_review\capacity_aware_supervised\policy.py');target='/joint/followup_review/capacity_aware_supervised/policy.py'},
    @{source=(Join-Path $joint 'followup_review\capacity_aware_supervised\seal_output.py');target='/joint/followup_review/capacity_aware_supervised/seal_output.py'},
    @{source=(Join-Path $joint 'followup_review\capacity_aware_rl\PRE_FIT_CONTRACT.md');target='/joint/followup_review/capacity_aware_rl/PRE_FIT_CONTRACT.md'},
    @{source=(Join-Path $joint 'followup_review\capacity_aware_rl\TRAIN_OUTPUT_SEAL.json');target='/joint/followup_review/capacity_aware_rl/TRAIN_OUTPUT_SEAL.json'},
    @{source=(Join-Path $joint 'followup_review\capacity_aware_rl\train_capacity_rl.py');target='/joint/followup_review/capacity_aware_rl/train_capacity_rl.py'}
)
foreach ($m in $files) {
    if (-not (Test-Path -LiteralPath $m.source -PathType Leaf)) { throw "MISSING_FROZEN_INPUT: $($m.source)" }
}
$dirs = @(
    @{source=(Join-Path $joint 'followup_review\capacity_aware_supervised\out');target='/joint/followup_review/capacity_aware_supervised/out'},
    @{source=(Join-Path $joint 'followup_review\capacity_aware_rl\out');target='/joint/followup_review/capacity_aware_rl/out'}
)
foreach ($m in $dirs) {
    if (-not (Test-Path -LiteralPath $m.source -PathType Container)) { throw "MISSING_FROZEN_MODEL_DIR: $($m.source)" }
}
$existing = & docker --context desktop-linux ps -a --filter "name=^/$name$" --format '{{.Names}}'
if ($LASTEXITCODE -ne 0) { throw 'CONTAINER_NAME_QUERY_FAILED' }
if ((@($existing) | Out-String).Trim() -eq $name) { throw "PRESERVE_EXISTING_CONTAINER: $name" }
$argv = @('create','--name',$name,'--pull=never','--network','none','--read-only',
          '--cap-drop','ALL','--security-opt','no-new-privileges',
          '--user','65532:65532','--memory','2g','--pids-limit','128','--cpus','2',
          '--tmpfs','/tmp:rw,noexec,nosuid,size=64m',
          '--env','PYTHONDONTWRITEBYTECODE=1','--env','PYTHONPATH=/joint',
          '--env','OMP_NUM_THREADS=2','--env','OPENBLAS_NUM_THREADS=2','--env','MKL_NUM_THREADS=2',
          '--workdir','/joint')
foreach ($m in $files) { $argv += @('--mount',"type=bind,source=$($m.source),target=$($m.target),readonly") }
foreach ($m in $dirs) { $argv += @('--mount',"type=bind,source=$($m.source),target=$($m.target),readonly") }
$argv += @('--mount',"type=bind,source=$out,target=/out")
$argv += @($Image,'python','-B','/joint/followup_review/capacity_aware_revision/replay_2025_capacity.py',
           $Phase,'--out','/out')
@{
    batch='a2_latest_effective_joint_20260927';phase=$Phase;endpoint=$endpoint
    requested_image=$Image;actual_image=$actualImage
    argv=@('docker','--context','desktop-linux')+$argv
    file_inputs=@($files | ForEach-Object {
        @{source=$_.source;target=$_.target;sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $_.source).Hash.ToLowerInvariant()}
    })
    model_dirs_ro=$dirs
    test_2026_source_mounts=0
} | ConvertTo-Json -Depth 9 | Set-Content -LiteralPath $commandPath -Encoding utf8
$created = & docker --context desktop-linux @argv 2>&1
$createCode = $LASTEXITCODE
if ($createCode -ne 0) {
    @{phase='create';exit_code=$createCode;output=@($created)} | ConvertTo-Json -Depth 5 |
        Set-Content -LiteralPath $receiptPath -Encoding utf8
    throw "2025_CONTAINER_CREATE_FAILED: $createCode $created"
}
$id = (@($created) | Select-Object -Last 1).ToString().Trim()
& docker --context desktop-linux inspect $id | Set-Content -LiteralPath $inspectPath -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw 'CONTAINER_INSPECT_FAILED' }
$started = & docker --context desktop-linux start $id 2>&1
$startCode = $LASTEXITCODE
if ($startCode -ne 0) { throw "CONTAINER_START_FAILED: $startCode $started" }
$waited = & docker --context desktop-linux wait $id 2>&1
$waitCode = $LASTEXITCODE
$containerExit = if ($waitCode -eq 0) { [int](@($waited) | Select-Object -Last 1).ToString().Trim() } else { $null }
$savedPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& docker --context desktop-linux logs $id *>&1 | Set-Content -LiteralPath $logPath -Encoding utf8
$logsCode = $LASTEXITCODE
$ErrorActionPreference = $savedPreference
& docker --context desktop-linux inspect $id | Set-Content -LiteralPath $inspectPath -Encoding utf8
@{
    container_id=$id;endpoint=$endpoint;requested_image=$Image;actual_image=$actualImage
    create_cli_exit_code=$createCode;start_cli_exit_code=$startCode
    wait_cli_exit_code=$waitCode;container_exit_code=$containerExit;logs_cli_exit_code=$logsCode
    freeze_sha256=if(Test-Path -LiteralPath (Join-Path $out 'PRE_REPLAY_FREEZE.json')){
        (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $out 'PRE_REPLAY_FREEZE.json')).Hash.ToLowerInvariant()
    }else{$null}
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receiptPath -Encoding utf8
Write-Output "2025_CAPACITY_$($Phase.ToUpperInvariant())_EXIT $containerExit CONTAINER $id"
if ($waitCode -ne 0 -or $containerExit -ne 0) { throw '2025_CAPACITY_PHASE_FAILED_PRESERVE_OUTPUT' }
