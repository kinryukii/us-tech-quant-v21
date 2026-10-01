param(
    [string]$Image = 'sha256:32365682bb6776c9f4e1abe936ab92bb7100696bc89576279d1a3c3fb9379bfe',
    [ValidateSet('01','02')][string]$Attempt = '01',
    [switch]$RecoverSaved
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$here = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$joint = (Resolve-Path -LiteralPath (Join-Path $here '..\..')).Path
$parent = Split-Path -Parent $joint
$suffix = if ($Attempt -eq '01') { '' } else { '_02' }
$out = Join-Path $here ("out$suffix")
$container = "joint-pre2026-capacity-20260927-$Attempt"
$config = Join-Path $here ("RUNTIME_COMMAND$suffix.json")
$inspect = Join-Path $here ("CONTAINER_INSPECT$suffix.json")
$log = Join-Path $here ("CONTAINER$suffix.log")
$receipt = Join-Path $here ("CONTAINER_RECEIPT$suffix.json")
$imageInspect = Join-Path $here ("IMAGE_INSPECT$suffix.json")
if ($RecoverSaved -and $Attempt -ne '02') { throw 'RECOVERY_REQUIRES_ATTEMPT_02' }

foreach ($p in @($config, $inspect, $log, $receipt, $imageInspect)) {
    if (Test-Path -LiteralPath $p) { throw "PRESERVE_EXISTING_CAPACITY_RUN: $p" }
}
if (Test-Path -LiteralPath $out) {
    if (@(Get-ChildItem -LiteralPath $out -Force).Count -ne 0) { throw 'CAPACITY_OUTPUT_NOT_EMPTY' }
} else {
    New-Item -ItemType Directory -Path $out | Out-Null
}
if ($env:DOCKER_HOST -or ($env:DOCKER_CONTEXT -and $env:DOCKER_CONTEXT -ne 'desktop-linux')) {
    throw 'UNAPPROVED_DOCKER_ENVIRONMENT_ENDPOINT'
}
$context = (& docker context show 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $context -ne 'desktop-linux') { throw "UNEXPECTED_DOCKER_CONTEXT: $context" }
$contextJson = & docker context inspect desktop-linux 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) { throw 'DOCKER_CONTEXT_INSPECT_FAILED' }
$endpoint = ((ConvertFrom-Json $contextJson)[0]).Endpoints.docker.Host
if ($endpoint -ne 'npipe:////./pipe/dockerDesktopLinuxEngine') {
    throw "NONLOCAL_DOCKER_ENDPOINT: $endpoint"
}

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
    @{ source=(Join-Path $here 'PRE2026_STUDY_CONTRACT.md'); target='/joint/followup_review/capacity/PRE2026_STUDY_CONTRACT.md' },
    @{ source=(Join-Path $here 'study_pre2026_capacity.py'); target='/joint/followup_review/capacity/study_pre2026_capacity.py' },
    @{ source=(Join-Path $joint 'data\pre2026_joint_context.parquet'); target='/joint/data/pre2026_joint_context.parquet' },
    @{ source=(Join-Path $parent 'a2_strict_method_retrain_20260926\results\pre2026_original_price_coordinate.parquet'); target='/a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet' },
    @{ source=(Join-Path $parent 'a2_strict_method_retrain_20260926\results\hgb\pre2026_oof.parquet'); target='/a2_strict_method_retrain_20260926/results/hgb/pre2026_oof.parquet' }
)
$dirs = @(
    @{ source=(Join-Path $joint 'joint_linear_tree_coverage_v2\out'); target='/joint/joint_linear_tree_coverage_v2/out' },
    @{ source=(Join-Path $joint 'joint_neural_artifacts'); target='/joint/joint_neural_artifacts' },
    @{ source=(Join-Path $joint 'evaluation_2025_sampling_v2\joint_hgb_10bps'); target='/joint/evaluation_2025_sampling_v2/joint_hgb_10bps' },
    @{ source=(Join-Path $joint 'evaluation_2025\joint_rl_ensemble_10bps'); target='/joint/evaluation_2025/joint_rl_ensemble_10bps' }
)
if ($RecoverSaved) {
    $mounts += @(
        @{ source=(Join-Path $here 'summarize_saved_pre2026_replays.py'); target='/joint/followup_review/capacity/summarize_saved_pre2026_replays.py' },
        @{ source=(Join-Path $here 'CONTAINER_RECEIPT.json'); target='/joint/followup_review/capacity/CONTAINER_RECEIPT.json' },
        @{ source=(Join-Path $here 'CONTAINER.log'); target='/joint/followup_review/capacity/CONTAINER.log' }
    )
    $dirs += @{ source=(Join-Path $here 'out'); target='/joint/followup_review/capacity/out' }
}
foreach ($m in $mounts) {
    if (-not (Test-Path -LiteralPath $m.source -PathType Leaf)) { throw "SOURCE_FILE_MISSING: $($m.source)" }
}
foreach ($d in $dirs) {
    if (-not (Test-Path -LiteralPath $d.source -PathType Container)) { throw "SOURCE_DIR_MISSING: $($d.source)" }
}
$existing = & docker --context desktop-linux container inspect $container 2>$null
if ($LASTEXITCODE -eq 0) { throw "CONTAINER_NAME_EXISTS: $container" }
$imageJson = & docker --context desktop-linux image inspect $Image
if ($LASTEXITCODE -ne 0) { throw 'FIXED_LOCAL_IMAGE_MISSING' }
$imageJson | Set-Content -LiteralPath $imageInspect -Encoding utf8

$argv = @('create', '--name', $container, '--pull=never', '--network', 'none',
          '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
          '--user', '65532:65532', '--memory', '2g', '--pids-limit', '128', '--cpus', '2',
          '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m',
          '--env', 'PYTHONDONTWRITEBYTECODE=1',
          '--env', 'OMP_NUM_THREADS=2', '--env', 'OPENBLAS_NUM_THREADS=2',
          '--env', 'MKL_NUM_THREADS=2', '--workdir', '/joint')
foreach ($m in @($mounts) + @($dirs)) {
    $argv += @('--mount', "type=bind,source=$($m.source),target=$($m.target),readonly")
}
$argv += @('--mount', "type=bind,source=$out,target=/joint/followup_review/capacity/out$suffix",
           $Image, 'python', '-B')
if ($RecoverSaved) {
    $argv += '/joint/followup_review/capacity/summarize_saved_pre2026_replays.py'
} else {
    $argv += @('/joint/followup_review/capacity/study_pre2026_capacity.py',
               '--output', "/joint/followup_review/capacity/out$suffix")
}
@{
    argv = @('docker', '--context', 'desktop-linux') + $argv
    image_id = $Image
    local_endpoint = $endpoint
    container_name = $container
    readonly_file_mounts = $mounts
    readonly_directory_mounts = $dirs
    private_output = $out
    scope = if ($RecoverSaved) { '2025 saved replay read-only recovery; no new replay or fit; no 2026 mount' } else {
        '2025 pretest capacity diagnostic only; no market fit; no 2026 mount'
    }
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $config -Encoding utf8

$created = & docker --context desktop-linux @argv 2>&1
$createCode = $LASTEXITCODE
if ($createCode -ne 0) {
    @{ phase='create'; cli_exit_code=$createCode; output=@($created) } |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receipt -Encoding utf8
    throw "CONTAINER_CREATE_FAILED: $createCode $created"
}
$id = (@($created) | Select-Object -Last 1).ToString().Trim()
$actualInspect = & docker --context desktop-linux inspect $id
$inspectCode = $LASTEXITCODE
$actualInspect | Set-Content -LiteralPath $inspect -Encoding utf8
if ($inspectCode -ne 0) { throw 'CONTAINER_INSPECT_FAILED' }
Write-Output "CAPACITY_CONTAINER_CREATED $id"

$started = & docker --context desktop-linux start $id 2>&1
$startCode = $LASTEXITCODE
if ($startCode -ne 0) {
    @{ phase='start'; container_id=$id; cli_exit_code=$startCode; output=@($started) } |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receipt -Encoding utf8
    throw "CONTAINER_START_FAILED: $startCode $started"
}
Write-Output "CAPACITY_CONTAINER_STARTED $id"
$waited = & docker --context desktop-linux wait $id 2>&1
$waitCode = $LASTEXITCODE
$exitCode = if ($waitCode -eq 0) { [int](@($waited) | Select-Object -Last 1).ToString().Trim() } else { $null }
& docker --context desktop-linux logs $id *>&1 | Set-Content -LiteralPath $log -Encoding utf8
$logCode = $LASTEXITCODE
& docker --context desktop-linux inspect $id | Set-Content -LiteralPath $inspect -Encoding utf8
$complete = Join-Path $out 'COMPLETE.json'
@{
    phase='finished'; container_id=$id; image_id=$Image; endpoint=$endpoint
    create_cli_exit_code=$createCode; inspect_cli_exit_code=$inspectCode
    start_cli_exit_code=$startCode; wait_cli_exit_code=$waitCode
    container_exit_code=$exitCode; logs_cli_exit_code=$logCode
    complete_exists=(Test-Path -LiteralPath $complete -PathType Leaf)
    complete_sha256=if (Test-Path -LiteralPath $complete -PathType Leaf) {
        (Get-FileHash -Algorithm SHA256 -LiteralPath $complete).Hash.ToLowerInvariant()
    } else { $null }
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receipt -Encoding utf8
Write-Output "CAPACITY_CONTAINER_EXIT $exitCode"
if ($waitCode -ne 0 -or $exitCode -ne 0 -or -not (Test-Path -LiteralPath $complete -PathType Leaf)) {
    throw 'CAPACITY_STUDY_FAILED_PRESERVE_CONTAINER_AND_OUTPUT'
}
