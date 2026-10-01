param(
    [string]$Image = 'sha256:32365682bb6776c9f4e1abe936ab92bb7100696bc89576279d1a3c3fb9379bfe'
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$here = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$joint = (Resolve-Path -LiteralPath (Join-Path $here '..\..')).Path
$parent = Split-Path -Parent $joint
$v2 = Join-Path $joint 'joint_linear_tree_coverage_v2\out'
$output = Join-Path $joint 'evaluation_2025_sampling_v2'
$container = 'joint-v2-2025-replay-20260927-01'
$config = Join-Path $here 'V2_2025_RUNTIME_COMMAND.json'
$inspect = Join-Path $here 'V2_2025_CONTAINER_INSPECT.json'
$imageInspect = Join-Path $here 'V2_2025_IMAGE_INSPECT.json'
$log = Join-Path $here 'V2_2025_CONTAINER.log'
$receipt = Join-Path $here 'V2_2025_CONTAINER_RECEIPT.json'

if (-not (Test-Path -LiteralPath (Join-Path $v2 'FIT_RECEIPT.json') -PathType Leaf)) {
    throw 'V2_FIT_RECEIPT_MISSING'
}
$fit = Get-Content -LiteralPath (Join-Path $v2 'FIT_RECEIPT.json') -Raw | ConvertFrom-Json
if ($fit.status -ne 'PASS' -or $fit.revision -ne 'DATE_COMPLETE_WITHIN_DAY_HASH_V2') {
    throw 'V2_FIT_RECEIPT_NOT_PASS'
}
foreach ($p in @($config, $inspect, $log, $receipt)) {
    if (Test-Path -LiteralPath $p) { throw "PRESERVE_EXISTING_RUN_EVIDENCE: $p" }
}
if (Test-Path -LiteralPath $output) {
    if (@(Get-ChildItem -LiteralPath $output -Force).Count -ne 0) {
        throw "V2_OUTPUT_NOT_EMPTY: $output"
    }
} else {
    New-Item -ItemType Directory -Path $output | Out-Null
}

# File-level readonly mounts expose only code and pre-2026 material the
# 2025 adapter consumes. No joint root, evaluation_2026, Docker socket,
# profile, or host cache is mounted.
$mounts = @(
    @{ source=(Join-Path $joint 'engine.py'); target='/joint/engine.py' },
    @{ source=(Join-Path $joint 'run_suite.py'); target='/joint/run_suite.py' },
    @{ source=(Join-Path $joint 'joint_linear_tree.py'); target='/joint/joint_linear_tree.py' },
    @{ source=(Join-Path $joint 'joint_neural.py'); target='/joint/joint_neural.py' },
    @{ source=(Join-Path $joint 'joint_risk.py'); target='/joint/joint_risk.py' },
    @{ source=(Join-Path $joint 'risk.py'); target='/joint/risk.py' },
    @{ source=(Join-Path $joint 'models\predict.py'); target='/joint/models/predict.py' },
    @{ source=(Join-Path $joint 'models\model_registry.json'); target='/joint/models/model_registry.json' },
    @{ source=(Join-Path $joint 'joint_linear_tree_coverage_v2\bundle\v2_policy.py'); target='/joint/joint_linear_tree_coverage_v2/bundle/v2_policy.py' },
    @{ source=(Join-Path $joint 'followup_review\cost\replay_2025_sampling_v2.py'); target='/joint/followup_review/cost/replay_2025_sampling_v2.py' },
    @{ source=(Join-Path $joint 'data\pre2026_joint_context.parquet'); target='/joint/data/pre2026_joint_context.parquet' },
    @{ source=(Join-Path $parent 'a2_strict_method_retrain_20260926\results\pre2026_original_price_coordinate.parquet'); target='/a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet' },
    @{ source=(Join-Path $parent 'a2_strict_method_retrain_20260926\results\hgb\pre2026_oof.parquet'); target='/a2_strict_method_retrain_20260926/results/hgb/pre2026_oof.parquet' },
    @{ source=(Join-Path $joint 'evaluation_2025\COMPLETE.json'); target='/joint/evaluation_2025/COMPLETE.json' },
    @{ source=(Join-Path $joint 'evaluation_2025\comparison.csv'); target='/joint/evaluation_2025/comparison.csv' }
)
foreach ($mount in $mounts) {
    if (-not (Test-Path -LiteralPath $mount.source -PathType Leaf)) {
        throw "SOURCE_MISSING: $($mount.source)"
    }
}
if (-not (Test-Path -LiteralPath $v2 -PathType Container)) { throw 'V2_MODEL_DIRECTORY_MISSING' }

$existing = & docker container inspect $container 2>$null
if ($LASTEXITCODE -eq 0) { throw "CONTAINER_NAME_EXISTS: $container" }
$imageJson = & docker image inspect $Image
if ($LASTEXITCODE -ne 0) { throw 'FIXED_IMAGE_NOT_PRESENT' }
$imageJson | Set-Content -LiteralPath $imageInspect -Encoding utf8

$arguments = @(
    'create', '--name', $container, '--pull=never',
    '--network', 'none', '--read-only', '--cap-drop', 'ALL',
    '--security-opt', 'no-new-privileges', '--user', '65532:65532',
    '--memory', '2g', '--pids-limit', '128', '--cpus', '2',
    '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m',
    '--env', 'PYTHONDONTWRITEBYTECODE=1',
    '--env', 'OMP_NUM_THREADS=2', '--env', 'OPENBLAS_NUM_THREADS=2',
    '--env', 'MKL_NUM_THREADS=2', '--workdir', '/joint'
)
foreach ($mount in $mounts) {
    $arguments += @('--mount', "type=bind,source=$($mount.source),target=$($mount.target),readonly")
}
$arguments += @(
    '--mount', "type=bind,source=$v2,target=/joint/joint_linear_tree_coverage_v2/out,readonly",
    '--mount', "type=bind,source=$output,target=/joint/evaluation_2025_sampling_v2",
    $Image,
    'python', '-B', '/joint/followup_review/cost/replay_2025_sampling_v2.py',
    '--v2-artifacts', '/joint/joint_linear_tree_coverage_v2/out',
    '--output', '/joint/evaluation_2025_sampling_v2'
)
@{
    argv = @('docker') + $arguments
    image_id = $Image
    container_name = $container
    readonly_file_mounts = $mounts
    readonly_model_directory = $v2
    private_output_directory = $output
    science = '2025 only; seven v2 estimators plus quantile-risk derived policy; original 10bp/$1m/1% ADV'
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $config -Encoding utf8

$created = & docker @arguments 2>&1
$createCode = $LASTEXITCODE
if ($createCode -ne 0) {
    @{ phase='create'; cli_exit_code=$createCode; output=@($created) } |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receipt -Encoding utf8
    throw "DOCKER_CREATE_FAILED: $createCode $created"
}
$containerId = (@($created) | Select-Object -Last 1).ToString().Trim()
$actualInspect = & docker inspect $containerId
$inspectCode = $LASTEXITCODE
$actualInspect | Set-Content -LiteralPath $inspect -Encoding utf8
if ($inspectCode -ne 0) { throw 'DOCKER_INSPECT_FAILED' }
Write-Output "V2_2025_CONTAINER_CREATED $containerId"

$started = & docker start $containerId 2>&1
$startCode = $LASTEXITCODE
if ($startCode -ne 0) {
    @{ phase='start'; container_id=$containerId; cli_exit_code=$startCode; output=@($started) } |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receipt -Encoding utf8
    throw "DOCKER_START_FAILED: $startCode $started"
}
Write-Output "V2_2025_CONTAINER_STARTED $containerId"
$waited = & docker wait $containerId 2>&1
$waitCliCode = $LASTEXITCODE
$containerExit = if ($waitCliCode -eq 0) { [int](@($waited) | Select-Object -Last 1).ToString().Trim() } else { $null }
& docker logs $containerId *>&1 | Set-Content -LiteralPath $log -Encoding utf8
$logsCode = $LASTEXITCODE
$finalInspect = & docker inspect $containerId
$finalInspect | Set-Content -LiteralPath $inspect -Encoding utf8
$complete = Join-Path $output 'COMPLETE.json'
$record = @{
    phase = 'finished'
    container_id = $containerId
    image_id = $Image
    create_cli_exit_code = $createCode
    inspect_cli_exit_code = $inspectCode
    start_cli_exit_code = $startCode
    wait_cli_exit_code = $waitCliCode
    container_exit_code = $containerExit
    logs_cli_exit_code = $logsCode
    complete_exists = (Test-Path -LiteralPath $complete -PathType Leaf)
    complete_sha256 = if (Test-Path -LiteralPath $complete -PathType Leaf) {
        (Get-FileHash -Algorithm SHA256 -LiteralPath $complete).Hash.ToLowerInvariant()
    } else { $null }
    output_directory = $output
}
$record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receipt -Encoding utf8
Write-Output "V2_2025_CONTAINER_EXIT $containerExit"
if ($waitCliCode -ne 0 -or $containerExit -ne 0 -or -not $record.complete_exists) {
    throw 'V2_2025_REPLAY_FAILED_PRESERVE_CONTAINER_AND_OUTPUT'
}
