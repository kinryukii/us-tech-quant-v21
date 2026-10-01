param([ValidateSet('prepare','fit')][string]$Phase)
$ErrorActionPreference = 'Stop'
$here = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$joint = (Resolve-Path -LiteralPath (Join-Path $here '..\..')).Path
$parent = Split-Path -Parent $joint
$image = 'sha256:32365682bb6776c9f4e1abe936ab92bb7100696bc89576279d1a3c3fb9379bfe'
$name = "joint-cap-hgb-$Phase-20260927-01"
$out = Join-Path $here 'out'
$config = Join-Path $here "$Phase.CREATE_ARGV.json"
$inspectPath = Join-Path $here "$Phase.CONTAINER_INSPECT.json"
$logPath = Join-Path $here "$Phase.CONTAINER.log"
$receiptPath = Join-Path $here "$Phase.CONTAINER_RECEIPT.json"
foreach ($path in @($config,$inspectPath,$logPath,$receiptPath)) {
    if (Test-Path -LiteralPath $path) { throw "PRESERVE_EXISTING_RUN:$path" }
}
if ($env:DOCKER_HOST -or ($env:DOCKER_CONTEXT -and $env:DOCKER_CONTEXT -ne 'desktop-linux')) {
    throw 'UNAPPROVED_DOCKER_ENDPOINT_ENV'
}
$context = (& docker context show | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $context -ne 'desktop-linux') { throw "UNEXPECTED_CONTEXT:$context" }
$endpoint = ((& docker context inspect desktop-linux | ConvertFrom-Json)[0]).Endpoints.docker.Host
if ($endpoint -ne 'npipe:////./pipe/dockerDesktopLinuxEngine') { throw "UNAPPROVED_ENDPOINT:$endpoint" }
if (-not (Test-Path -LiteralPath $out)) { New-Item -ItemType Directory -Path $out | Out-Null }
if ($Phase -eq 'prepare' -and @(Get-ChildItem -LiteralPath $out -Force).Count -ne 0) {
    throw 'PREPARE_REQUIRES_EMPTY_OUTPUT'
}
if ($Phase -eq 'fit' -and -not (Test-Path -LiteralPath (Join-Path $out 'PRE_FIT_FREEZE.json'))) {
    throw 'MISSING_PRE_FIT_FREEZE'
}
$existing = & docker --context desktop-linux container inspect $name 2>$null
if ($LASTEXITCODE -eq 0) { throw "CONTAINER_NAME_EXISTS:$name" }
$mounts = @(
    @{source=(Join-Path $joint 'engine.py');target='/joint/engine.py'},
    @{source=(Join-Path $joint 'joint_linear_tree.py');target='/joint/joint_linear_tree.py'},
    @{source=(Join-Path $joint 'models\model_registry.json');target='/joint/models/model_registry.json'},
    @{source=(Join-Path $joint 'data\pre2026_joint_context.parquet');target='/joint/data/pre2026_joint_context.parquet'},
    @{source=(Join-Path $parent 'a2_strict_method_retrain_20260926\results\pre2026_original_price_coordinate.parquet');target='/external/pre2026_original_price_coordinate.parquet'},
    @{source=(Join-Path $parent 'a2_strict_method_retrain_20260926\results\hgb\pre2026_oof.parquet');target='/external/pre2026_oof.parquet'},
    @{source=(Join-Path $parent 'a2_strict_method_retrain_20260926\results\hgb\fit_log.json');target='/external/fit_log.json'},
    @{source=(Join-Path $joint 'joint_linear_tree_coverage_v2\out\sample_keys_validation.parquet');target='/joint/joint_linear_tree_coverage_v2/out/sample_keys_validation.parquet'},
    @{source=(Join-Path $joint 'joint_linear_tree_coverage_v2\out\sample_keys_final.parquet');target='/joint/joint_linear_tree_coverage_v2/out/sample_keys_final.parquet'},
    @{source=(Join-Path $joint 'joint_linear_tree_coverage_v2\out\sample_keys_validation_metrics.parquet');target='/joint/joint_linear_tree_coverage_v2/out/sample_keys_validation_metrics.parquet'},
    @{source=(Join-Path $here 'SCIENCE_CONTRACT.md');target='/joint/followup_review/capacity_aware_supervised/SCIENCE_CONTRACT.md'},
    @{source=(Join-Path $here 'one_step_label.py');target='/joint/followup_review/capacity_aware_supervised/one_step_label.py'},
    @{source=(Join-Path $here 'verify_one_step.py');target='/joint/followup_review/capacity_aware_supervised/verify_one_step.py'},
    @{source=(Join-Path $here 'prepare_fit.py');target='/joint/followup_review/capacity_aware_supervised/prepare_fit.py'},
    @{source=(Join-Path $here 'policy.py');target='/joint/followup_review/capacity_aware_supervised/policy.py'}
)
$technical = Join-Path $here 'technical_out_01\TECHNICAL_CHECK.json'
if (-not (Test-Path -LiteralPath $technical -PathType Leaf)) { throw 'SYNTHETIC_ENGINE_CHECK_MISSING' }
$mounts += @{source=$technical;target='/technical/TECHNICAL_CHECK.json'}
foreach ($item in $mounts) {
    if (-not (Test-Path -LiteralPath $item.source -PathType Leaf)) { throw "SOURCE_FILE_MISSING:$($item.source)" }
}
$argv = @('create','--name',$name,'--pull=never','--network','none','--read-only',
          '--cap-drop','ALL','--security-opt','no-new-privileges',
          '--user','65532:65532','--memory','2g','--pids-limit','128','--cpus','2',
          '--tmpfs','/tmp:rw,noexec,nosuid,size=64m',
          '--env','PYTHONDONTWRITEBYTECODE=1','--env','OMP_NUM_THREADS=2',
          '--env','OPENBLAS_NUM_THREADS=2','--env','MKL_NUM_THREADS=2',
          '--workdir','/joint')
foreach ($item in $mounts) {
    $argv += @('--mount',"type=bind,source=$($item.source),target=$($item.target),readonly")
}
$argv += @('--mount',"type=bind,source=$out,target=/out",
           $image,'python','-B','/joint/followup_review/capacity_aware_supervised/prepare_fit.py',$Phase)
@{argv=@('docker','--context','desktop-linux')+$argv;endpoint=$endpoint;files=$mounts;
  output=$out;phase=$Phase;image_id=$image;scope='pre2026 only; no 2026 mount'} |
    ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $config -Encoding utf8
$created = & docker --context desktop-linux @argv
if ($LASTEXITCODE -ne 0) { throw "DOCKER_CREATE_FAILED:$LASTEXITCODE" }
$id = (@($created) | Select-Object -Last 1).ToString().Trim()
$inspection = & docker --context desktop-linux inspect $id
$inspection | Set-Content -LiteralPath $inspectPath -Encoding utf8
$actual = ($inspection | ConvertFrom-Json)[0]
$destinations = @($actual.Mounts | ForEach-Object Destination | Sort-Object)
$expected = @($mounts | ForEach-Object { $_.target }) + '/out' | Sort-Object
if ($actual.Image -ne $image -or $actual.HostConfig.NetworkMode -ne 'none' -or
    -not $actual.HostConfig.ReadonlyRootfs -or $actual.HostConfig.Privileged -or
    $actual.Config.User -ne '65532:65532' -or $actual.HostConfig.Memory -ne 2147483648 -or
    ($destinations -join ',') -ne ($expected -join ',') -or
    @($actual.Mounts | Where-Object { $_.Destination -ne '/out' -and $_.RW }).Count -ne 0) {
    throw 'ACTUAL_CONTAINER_ISOLATION_MISMATCH'
}
& docker --context desktop-linux start $id | Out-Null
$startCode = $LASTEXITCODE
$wait = & docker --context desktop-linux wait $id
$waitCode = $LASTEXITCODE
$exitCode = if ($waitCode -eq 0) { [int](@($wait) | Select-Object -Last 1) } else { $null }
& docker --context desktop-linux logs $id *>&1 | Set-Content -LiteralPath $logPath -Encoding utf8
$completeName = if ($Phase -eq 'prepare') { 'PRE_FIT_FREEZE.json' } else { 'FIT_RECEIPT.json' }
$complete = Join-Path $out $completeName
$fits = 0
$partial = Join-Path $out 'FIT_RECEIPT.partial.json'
if ($Phase -eq 'fit') {
    if (Test-Path -LiteralPath $complete) { $fits = (Get-Content -Raw -LiteralPath $complete | ConvertFrom-Json).fit_calls }
    elseif (Test-Path -LiteralPath $partial) { $fits = (Get-Content -Raw -LiteralPath $partial | ConvertFrom-Json).fit_calls }
}
@{phase=$Phase;container_id=$id;image_id=$image;endpoint=$endpoint;
  start_cli_exit=$startCode;wait_cli_exit=$waitCode;container_exit=$exitCode;
  market_fit_calls=$fits;test_2026_reads=0;complete_exists=(Test-Path -LiteralPath $complete);
  complete_sha256=if (Test-Path -LiteralPath $complete) {
      (Get-FileHash -Algorithm SHA256 -LiteralPath $complete).Hash.ToLowerInvariant()
  } else { $null }} | ConvertTo-Json -Depth 5 |
    Set-Content -LiteralPath $receiptPath -Encoding utf8
if ($exitCode -ne 0 -or -not (Test-Path -LiteralPath $complete)) {
    throw "SUPERVISED_$($Phase.ToUpper())_FAILED_PRESERVE_OUTPUT:$exitCode"
}
Write-Output "CAPACITY_HGB_${Phase}_PASS $id"
