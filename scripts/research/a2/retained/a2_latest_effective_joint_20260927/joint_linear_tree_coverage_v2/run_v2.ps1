param([ValidateSet('canary','prepare','train','repair_prepare','repair_train','verify')][string]$Phase)
$ErrorActionPreference = 'Stop'
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
$batch = Split-Path -Parent $base
$bundle = Join-Path $base 'bundle'
$out = Join-Path $base 'out'
$data = Join-Path $batch 'data\pre2026_joint.parquet'
$image = 'sha256:32365682bb6776c9f4e1abe936ab92bb7100696bc89576279d1a3c3fb9379bfe'
$name = "joint-v2-$Phase-20260927"
$receiptPath = Join-Path $base "$Phase.CONTAINER_RECEIPT.json"
if (Test-Path -LiteralPath $receiptPath) { throw "PHASE_RECEIPT_EXISTS:$Phase" }
$cmd = if ($Phase -eq 'canary') {
    @('python3','-B','-c',"import sklearn,pandas,numpy,pyarrow,joblib; from pathlib import Path; assert Path('/data/pre2026_joint.parquet').is_file(); assert not Path('/evaluation_2026').exists(); assert Path('/out').is_dir(); print('PRE2026_ONLY_IMPORT_PASS', sklearn.__version__, pandas.__version__)")
} elseif ($Phase -eq 'repair_prepare') {
    @('python3','-B','/bundle/refine_coverage_v2_elastic.py','prepare')
} elseif ($Phase -eq 'repair_train') {
    @('python3','-B','/bundle/refine_coverage_v2_elastic.py','train')
} elseif ($Phase -eq 'verify') {
    @('python3','-B','/bundle/verify_coverage_v2.py')
} else { @('python3','-B','/bundle/retrain_coverage_v2.py',$Phase) }
$dockerArgs = @('create','--pull=never','--name',$name,'--network','none','--read-only',
    '--cap-drop','ALL','--security-opt','no-new-privileges','--memory','4g',
    '--pids-limit','256','--cpus','2','--user','65532:65532',
    '--tmpfs','/tmp:rw,noexec,nosuid,size=256m',
    '--mount',"type=bind,source=$bundle,target=/bundle,readonly",
    '--mount',"type=bind,source=$data,target=/data/pre2026_joint.parquet,readonly",
    '--mount',"type=bind,source=$out,target=/out",
    '-e','PYTHONDONTWRITEBYTECODE=1','-e',"R1_FIXED_IMAGE_ID=$image",$image) + $cmd
$argvPath = Join-Path $base "$Phase.CREATE_ARGV.json"
[System.IO.File]::WriteAllText($argvPath,($dockerArgs | ConvertTo-Json -Depth 6),[System.Text.Encoding]::UTF8)
& docker @dockerArgs | Out-Null
if ($LASTEXITCODE -ne 0) { throw "DOCKER_CREATE_FAILED:$LASTEXITCODE" }
$inspectPath = Join-Path $base "$Phase.CONTAINER_INSPECT.json"
$inspect = & docker inspect $name
if ($LASTEXITCODE -ne 0) { throw "DOCKER_INSPECT_FAILED:$LASTEXITCODE" }
[System.IO.File]::WriteAllText($inspectPath,($inspect -join "`n"),[System.Text.Encoding]::UTF8)
$i = ($inspect -join "`n" | ConvertFrom-Json)[0]
$destinations = @($i.Mounts | ForEach-Object { $_.Destination } | Sort-Object)
if ($i.Image -ne $image -or $i.HostConfig.NetworkMode -ne 'none' -or
    -not $i.HostConfig.ReadonlyRootfs -or $i.HostConfig.Privileged -or
    $i.Config.User -ne '65532:65532' -or $i.HostConfig.Memory -ne 4294967296 -or
    $i.HostConfig.PidsLimit -ne 256 -or
    ($destinations -join ',') -ne '/bundle,/data/pre2026_joint.parquet,/out' -or
    ($i.Mounts | Where-Object { $_.Destination -in @('/bundle','/data/pre2026_joint.parquet') -and $_.RW }).Count -gt 0) {
    throw 'ACTUAL_CONTAINER_ISOLATION_MISMATCH'
}
& docker start -a $name
$startCode = $LASTEXITCODE
$waitOutput = & docker wait $name
$waitCode = $LASTEXITCODE
$logs = & docker logs $name 2>&1
$logPath = Join-Path $base "$Phase.CONTAINER_LOG.txt"
[System.IO.File]::WriteAllText($logPath,($logs -join "`n"),[System.Text.Encoding]::UTF8)
$after = & docker inspect $name
$afterPath = Join-Path $base "$Phase.CONTAINER_FINAL_INSPECT.json"
[System.IO.File]::WriteAllText($afterPath,($after -join "`n"),[System.Text.Encoding]::UTF8)
$fitCount = 0
if ($Phase -eq 'train') {
    $fitReceipt = Join-Path $out 'FIT_RECEIPT.json'
    $partialReceipt = Join-Path $out 'FIT_RECEIPT.partial.json'
    if (Test-Path -LiteralPath $fitReceipt) { $fitCount = (Get-Content -Raw -LiteralPath $fitReceipt | ConvertFrom-Json).fit_calls }
    elseif (Test-Path -LiteralPath $partialReceipt) { $fitCount = (Get-Content -Raw -LiteralPath $partialReceipt | ConvertFrom-Json).fit_calls }
}
if ($Phase -eq 'repair_train') {
    $repairReceipt = Join-Path $out 'ELASTIC_REPAIR_RECEIPT.json'
    $repairPartial = Join-Path $out 'ELASTIC_REPAIR.partial.json'
    if (Test-Path -LiteralPath $repairReceipt) { $fitCount = (Get-Content -Raw -LiteralPath $repairReceipt | ConvertFrom-Json).additional_fit_calls }
    elseif (Test-Path -LiteralPath $repairPartial) { $fitCount = @(Get-Content -Raw -LiteralPath $repairPartial | ConvertFrom-Json).Count }
}
$receipt = [ordered]@{phase=$Phase; container=$name; image=$image; start_cli_exit=$startCode;
    wait_cli_exit=$waitCode; container_exit=([int]($waitOutput | Select-Object -Last 1));
    prestart_inspect=$inspectPath; final_inspect=$afterPath; log=$logPath;
    market_fit_count=$fitCount}
[System.IO.File]::WriteAllText($receiptPath,($receipt | ConvertTo-Json -Depth 6),[System.Text.Encoding]::UTF8)
if ($waitCode -ne 0 -or $receipt.container_exit -ne 0) { throw "PHASE_FAILED:${Phase}:$($receipt.container_exit)" }
Write-Output "PHASE_PASS:${Phase}:CONTAINER_EXIT_0"
