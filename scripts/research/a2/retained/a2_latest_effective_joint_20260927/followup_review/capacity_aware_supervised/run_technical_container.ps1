$ErrorActionPreference = 'Stop'
$here = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$joint = (Resolve-Path -LiteralPath (Join-Path $here '..\..')).Path
$image = 'sha256:32365682bb6776c9f4e1abe936ab92bb7100696bc89576279d1a3c3fb9379bfe'
$name = 'joint-cap-supervised-tech-20260927-01'
$out = Join-Path $here 'technical_out_01'
if ($env:DOCKER_HOST -or ($env:DOCKER_CONTEXT -and $env:DOCKER_CONTEXT -ne 'desktop-linux')) { throw 'UNAPPROVED_DOCKER_ENDPOINT_ENV' }
$context = (& docker context show | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $context -ne 'desktop-linux') { throw "UNEXPECTED_CONTEXT:$context" }
$endpoint = ((& docker context inspect desktop-linux | ConvertFrom-Json)[0]).Endpoints.docker.Host
if ($endpoint -ne 'npipe:////./pipe/dockerDesktopLinuxEngine') { throw "UNAPPROVED_ENDPOINT:$endpoint" }
if (Test-Path -LiteralPath $out) {
    if (@(Get-ChildItem -LiteralPath $out -Force).Count -ne 0) { throw 'TECHNICAL_OUTPUT_EXISTS' }
} else { New-Item -ItemType Directory -Path $out | Out-Null }
$existing = & docker --context desktop-linux container inspect $name 2>$null
if ($LASTEXITCODE -eq 0) { throw 'TECHNICAL_CONTAINER_EXISTS' }
$files = @(
    @{source=(Join-Path $joint 'engine.py');target='/joint/engine.py'},
    @{source=(Join-Path $here 'one_step_label.py');target='/joint/followup_review/capacity_aware_supervised/one_step_label.py'},
    @{source=(Join-Path $here 'verify_one_step.py');target='/joint/followup_review/capacity_aware_supervised/verify_one_step.py'}
)
$argv = @('create','--name',$name,'--pull=never','--network','none','--read-only',
          '--cap-drop','ALL','--security-opt','no-new-privileges','--user','65532:65532',
          '--memory','1g','--pids-limit','64','--cpus','2',
          '--tmpfs','/tmp:rw,noexec,nosuid,size=64m',
          '--env','PYTHONDONTWRITEBYTECODE=1','--workdir','/joint')
foreach ($file in $files) { $argv += @('--mount',"type=bind,source=$($file.source),target=$($file.target),readonly") }
$argv += @('--mount',"type=bind,source=$out,target=/out",$image,'python','-B',
           '/joint/followup_review/capacity_aware_supervised/verify_one_step.py')
@{argv=@('docker','--context','desktop-linux')+$argv;endpoint=$endpoint;files=$files;output=$out} |
    ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $here 'technical.CREATE_ARGV.json') -Encoding utf8
$created = & docker --context desktop-linux @argv
if ($LASTEXITCODE -ne 0) { throw "DOCKER_CREATE_FAILED:$LASTEXITCODE" }
$id = (@($created) | Select-Object -Last 1).ToString().Trim()
$inspection = & docker --context desktop-linux inspect $id
$inspection | Set-Content -LiteralPath (Join-Path $here 'technical.CONTAINER_INSPECT.json') -Encoding utf8
$actual = ($inspection | ConvertFrom-Json)[0]
$destinations = @($actual.Mounts | ForEach-Object Destination | Sort-Object)
if ($actual.Image -ne $image -or $actual.HostConfig.NetworkMode -ne 'none' -or
    -not $actual.HostConfig.ReadonlyRootfs -or $actual.HostConfig.Privileged -or
    $actual.Config.User -ne '65532:65532' -or $actual.HostConfig.Memory -ne 1073741824 -or
    ($destinations -join ',') -ne '/joint/engine.py,/joint/followup_review/capacity_aware_supervised/one_step_label.py,/joint/followup_review/capacity_aware_supervised/verify_one_step.py,/out' -or
    @($actual.Mounts | Where-Object { $_.Destination -ne '/out' -and $_.RW }).Count -ne 0) {
    throw 'ACTUAL_ISOLATION_MISMATCH'
}
& docker --context desktop-linux start $id | Out-Null
$startCode = $LASTEXITCODE
$wait = & docker --context desktop-linux wait $id
$waitCode = $LASTEXITCODE
$exitCode = if ($waitCode -eq 0) { [int](@($wait) | Select-Object -Last 1) } else { $null }
& docker --context desktop-linux logs $id *>&1 |
    Set-Content -LiteralPath (Join-Path $here 'technical.CONTAINER.log') -Encoding utf8
@{container_id=$id;image_id=$image;endpoint=$endpoint;start_cli_exit=$startCode;
  wait_cli_exit=$waitCode;container_exit=$exitCode;fit_calls=0;test_2026_reads=0} |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $here 'technical.CONTAINER_RECEIPT.json') -Encoding utf8
if ($exitCode -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $out 'TECHNICAL_CHECK.json'))) {
    throw "TECHNICAL_CHECK_FAILED:$exitCode"
}
Write-Output "SUPERVISED_STEP_TECHNICAL_PASS $id"
