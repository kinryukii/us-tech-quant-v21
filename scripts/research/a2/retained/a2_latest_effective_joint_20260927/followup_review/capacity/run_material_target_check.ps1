$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$here = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$joint = (Resolve-Path -LiteralPath (Join-Path $here '..\..')).Path
$out = Join-Path $here 'out_03'
$image = 'sha256:32365682bb6776c9f4e1abe936ab92bb7100696bc89576279d1a3c3fb9379bfe'
$name = 'joint-pre2026-capacity-targetcheck-20260927-03'
$receipt = Join-Path $here 'TARGET_CHECK_CONTAINER_RECEIPT.json'
$inspect = Join-Path $here 'TARGET_CHECK_CONTAINER_INSPECT.json'
$log = Join-Path $here 'TARGET_CHECK_CONTAINER.log'
$config = Join-Path $here 'TARGET_CHECK_RUNTIME_COMMAND.json'
foreach ($p in @($receipt, $inspect, $log, $config)) {
    if (Test-Path -LiteralPath $p) { throw "PRESERVE_EXISTING_TARGET_CHECK: $p" }
}
if (Test-Path -LiteralPath $out) {
    if (@(Get-ChildItem -LiteralPath $out -Force).Count -ne 0) { throw 'TARGET_CHECK_OUTPUT_NOT_EMPTY' }
} else { New-Item -ItemType Directory -Path $out | Out-Null }
if ($env:DOCKER_HOST -or ($env:DOCKER_CONTEXT -and $env:DOCKER_CONTEXT -ne 'desktop-linux')) {
    throw 'UNAPPROVED_DOCKER_ENVIRONMENT_ENDPOINT'
}
$context = (& docker context show 2>&1 | Out-String).Trim()
$endpoint = ((& docker context inspect desktop-linux | ConvertFrom-Json)[0]).Endpoints.docker.Host
if ($context -ne 'desktop-linux' -or $endpoint -ne 'npipe:////./pipe/dockerDesktopLinuxEngine') {
    throw "UNAPPROVED_DOCKER_ENDPOINT: $context $endpoint"
}
$mounts = @(
    @{ source=(Join-Path $here 'material_target_differences.py'); target='/joint/followup_review/capacity/material_target_differences.py' },
    @{ source=(Join-Path $here 'out\PRE_RUN_FREEZE.json'); target='/joint/followup_review/capacity/out/PRE_RUN_FREEZE.json' },
    @{ source=(Join-Path $here 'out_02\PRE_RECOVERY_FREEZE.json'); target='/joint/followup_review/capacity/out_02/PRE_RECOVERY_FREEZE.json' },
    @{ source=(Join-Path $here 'out_02\COMPLETE.json'); target='/joint/followup_review/capacity/out_02/COMPLETE.json' },
    @{ source=(Join-Path $joint 'evaluation_2025_sampling_v2\joint_hgb_10bps\target_decisions.parquet'); target='/joint/evaluation_2025_sampling_v2/joint_hgb_10bps/target_decisions.parquet' },
    @{ source=(Join-Path $joint 'evaluation_2025\joint_rl_ensemble_10bps\target_decisions.parquet'); target='/joint/evaluation_2025/joint_rl_ensemble_10bps/target_decisions.parquet' },
    @{ source=(Join-Path $here 'out\joint_hgb_no_capacity\target_decisions.parquet'); target='/joint/followup_review/capacity/out/joint_hgb_no_capacity/target_decisions.parquet' },
    @{ source=(Join-Path $here 'out\joint_rl_ensemble_no_capacity\target_decisions.parquet'); target='/joint/followup_review/capacity/out/joint_rl_ensemble_no_capacity/target_decisions.parquet' }
)
foreach ($m in $mounts) {
    if (-not (Test-Path -LiteralPath $m.source -PathType Leaf)) { throw "TARGET_CHECK_INPUT_MISSING: $($m.source)" }
}
$existing = & docker --context desktop-linux container inspect $name 2>$null
if ($LASTEXITCODE -eq 0) { throw 'TARGET_CHECK_CONTAINER_EXISTS' }
$found = & docker --context desktop-linux image inspect $image
if ($LASTEXITCODE -ne 0) { throw 'FIXED_IMAGE_MISSING' }
$argv = @('create', '--name', $name, '--pull=never', '--network', 'none', '--read-only',
          '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--user', '65532:65532',
          '--memory', '512m', '--pids-limit', '64', '--cpus', '1',
          '--tmpfs', '/tmp:rw,noexec,nosuid,size=32m',
          '--env', 'PYTHONDONTWRITEBYTECODE=1', '--workdir', '/joint')
foreach ($m in $mounts) { $argv += @('--mount', "type=bind,source=$($m.source),target=$($m.target),readonly") }
$argv += @('--mount', "type=bind,source=$out,target=/joint/followup_review/capacity/out_03",
           $image, 'python', '-B', '/joint/followup_review/capacity/material_target_differences.py')
@{ argv=@('docker','--context','desktop-linux')+$argv; endpoint=$endpoint;
   image_id=$image; readonly_file_mounts=$mounts; private_output=$out;
   scope='2025 saved target traces only; no replay, fit, or 2026 access' } |
    ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $config -Encoding utf8
$created = & docker --context desktop-linux @argv 2>&1
$createCode = $LASTEXITCODE
if ($createCode -ne 0) { throw "TARGET_CHECK_CREATE_FAILED: $created" }
$id = (@($created) | Select-Object -Last 1).ToString().Trim()
& docker --context desktop-linux inspect $id | Set-Content -LiteralPath $inspect -Encoding utf8
$inspectCode = $LASTEXITCODE
if ($inspectCode -ne 0) { throw 'TARGET_CHECK_INSPECT_FAILED' }
$started = & docker --context desktop-linux start $id 2>&1
$startCode = $LASTEXITCODE
if ($startCode -ne 0) { throw "TARGET_CHECK_START_FAILED: $started" }
$waited = & docker --context desktop-linux wait $id 2>&1
$waitCode = $LASTEXITCODE
$exitCode = if ($waitCode -eq 0) { [int](@($waited) | Select-Object -Last 1).ToString().Trim() } else { $null }
& docker --context desktop-linux logs $id *>&1 | Set-Content -LiteralPath $log -Encoding utf8
$logCode = $LASTEXITCODE
& docker --context desktop-linux inspect $id | Set-Content -LiteralPath $inspect -Encoding utf8
$result = Join-Path $out 'MATERIAL_TARGET_DIFFERENCES.json'
@{ container_id=$id; container_exit_code=$exitCode; create_cli_exit_code=$createCode;
   inspect_cli_exit_code=$inspectCode; start_cli_exit_code=$startCode;
   wait_cli_exit_code=$waitCode; logs_cli_exit_code=$logCode;
   result_exists=(Test-Path -LiteralPath $result -PathType Leaf);
   result_sha256=if (Test-Path -LiteralPath $result -PathType Leaf) {
       (Get-FileHash -Algorithm SHA256 -LiteralPath $result).Hash.ToLowerInvariant()
   } else { $null } } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $receipt -Encoding utf8
Write-Output "TARGET_CHECK_CONTAINER_EXIT $exitCode"
if ($exitCode -ne 0 -or -not (Test-Path -LiteralPath $result -PathType Leaf)) { throw 'TARGET_CHECK_FAILED' }
