$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$joint = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$here = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$out = Join-Path $here 'technical_20260927_01'
if (Test-Path -LiteralPath $out) { throw 'PRESERVE_EXISTING_NAV_CONTEXT_TEST' }
New-Item -ItemType Directory -Path $out | Out-Null
$image = 'sha256:32365682bb6776c9f4e1abe936ab92bb7100696bc89576279d1a3c3fb9379bfe'
$name = 'joint-nav-context-synthetic-20260927-01'
$context = (& docker context show 2>&1 | Select-Object -Last 1).ToString().Trim()
if ($LASTEXITCODE -ne 0) { throw 'DOCKER_CONTEXT_QUERY_FAILED' }
$endpoint = (& docker context inspect $context --format '{{.Endpoints.docker.Host}}' 2>&1 | Select-Object -Last 1).ToString().Trim()
if ($LASTEXITCODE -ne 0 -or $endpoint -ne 'npipe:////./pipe/dockerDesktopLinuxEngine') { throw "WRONG_DOCKER_ENDPOINT: $endpoint" }
$actualImage = (& docker image inspect --format '{{.Id}}' $image 2>&1 | Select-Object -Last 1).ToString().Trim()
if ($LASTEXITCODE -ne 0 -or $actualImage -ne $image) { throw 'FIXED_IMAGE_MISSING' }
$files = @(
    'engine.py',
    'followup_review/capacity_aware_revision/nav_context_adapter.py',
    'followup_review/capacity_aware_revision/test_nav_context_adapter.py'
)
$hashes = @{}
$argsDocker = @('create','--name',$name,'--pull=never','--network','none','--read-only',
    '--cap-drop','ALL','--security-opt','no-new-privileges','--user','65532:65532',
    '--memory','512m','--pids-limit','64','--cpus','1',
    '--tmpfs','/tmp:rw,noexec,nosuid,size=32m',
    '--env','PYTHONDONTWRITEBYTECODE=1','--workdir','/joint')
foreach ($rel in $files) {
    $src = Join-Path $joint $rel.Replace('/','\')
    if (-not (Test-Path -LiteralPath $src -PathType Leaf)) { throw "MISSING_INPUT: $src" }
    $hashes[$rel] = (Get-FileHash -LiteralPath $src -Algorithm SHA256).Hash.ToLowerInvariant()
    $argsDocker += @('--mount',"type=bind,source=$src,target=/joint/$rel,readonly")
}
if ($hashes['engine.py'] -ne 'c3bf057173960920de8faa15d6aa6e2522b1c8e9eae6bb3b4e96c665a37b33ff') {
    throw 'FROZEN_ENGINE_HASH_MISMATCH'
}
$argsDocker += @($image,'python','-B','/joint/followup_review/capacity_aware_revision/test_nav_context_adapter.py')
@{ docker_argv=@('docker')+$argsDocker; endpoint=$endpoint; image_id=$image; inputs_sha256=$hashes } |
    ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $out 'COMMAND.json') -Encoding utf8
$created = & docker @argsDocker 2>&1
$createCode = $LASTEXITCODE
if ($createCode -ne 0) { throw "CREATE_FAILED: $createCode $created" }
$id = (@($created) | Select-Object -Last 1).ToString().Trim()
(& docker inspect $id) | Set-Content -LiteralPath (Join-Path $out 'INSPECT.json') -Encoding utf8
$started = & docker start $id 2>&1
$startCode = $LASTEXITCODE
if ($startCode -ne 0) { throw "START_FAILED: $startCode $started" }
$waited = & docker wait $id 2>&1
$waitCode = $LASTEXITCODE
$containerExit = if ($waitCode -eq 0) { [int](@($waited) | Select-Object -Last 1).ToString().Trim() } else { $null }
& docker logs $id *>&1 | Set-Content -LiteralPath (Join-Path $out 'LOG.txt') -Encoding utf8
$logsCode = $LASTEXITCODE
(& docker inspect $id) | Set-Content -LiteralPath (Join-Path $out 'INSPECT.json') -Encoding utf8
@{ container_id=$id; endpoint=$endpoint; image_id=$image; create_cli_exit_code=$createCode;
    start_cli_exit_code=$startCode; wait_cli_exit_code=$waitCode; container_exit_code=$containerExit;
    logs_cli_exit_code=$logsCode; input_sha256=$hashes } |
    ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $out 'RECEIPT.json') -Encoding utf8
Write-Output "NAV_CONTEXT_TECHNICAL_EXIT $containerExit CONTAINER $id"
if ($containerExit -ne 0) { throw 'NAV_CONTEXT_TECHNICAL_FAILED_PRESERVE_EVIDENCE' }
