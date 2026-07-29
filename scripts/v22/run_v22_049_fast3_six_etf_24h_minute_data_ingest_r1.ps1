[CmdletBinding()]
param([switch]$Execute,[switch]$FullRefresh,[switch]$PreflightOnly,[switch]$IncrementalOnly)
$ErrorActionPreference='Stop'
if (-not $Execute -and -not $PreflightOnly) { throw 'Specify -Execute or -PreflightOnly.' }
$repo=(Resolve-Path (Join-Path $PSScriptRoot '..\\..')).Path
$cfg=Get-Content (Join-Path $repo 'config\\v22_049_fast3_six_etf_24h_minute_data_ingest_r1.json') -Raw | ConvertFrom-Json
if (-not (Test-NetConnection $cfg.host -Port $cfg.port -InformationLevel Quiet)) { throw "OpenD unavailable at $($cfg.host):$($cfg.port)" }
$py='D:\us-tech-quant-envs\abcde-moomoo-sdk-10.8.6808\Scripts\python.exe'; if(-not(Test-Path $py)){throw "Moomoo SDK Python unavailable: $py"}
$exe='C:\Users\Lenovo\AppData\Roaming\moomoo_OpenD\moomoo_OpenD.exe'; if(Test-Path $exe){$env:MOOMOO_OPEND_VERSION=(Get-Item $exe).VersionInfo.ProductVersion}
$args=@((Join-Path $repo 'scripts\\v22\\v22_049_fast3_six_etf_24h_minute_data_ingest_r1.py')); if($FullRefresh){$args+='--full-refresh'}; if($PreflightOnly){$args+='--preflight-only'}; if($IncrementalOnly){$args+='--incremental-only'}
& $py @args; if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
$summary=Join-Path $repo 'outputs\\v22\\V22.049_FAST3_SIX_ETF_24H_MINUTE_DATA_INGEST_R1\\v22_049_summary.json'; if(-not(Test-Path $summary)){throw "Summary missing: $summary"}; Get-Content $summary -Raw; exit 0
