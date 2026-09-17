[CmdletBinding(DefaultParameterSetName='DryRun')]
param(
    [Parameter(ParameterSetName='DryRun')][switch]$DryRun,
    [Parameter(ParameterSetName='Execute')][switch]$Execute,
    [Parameter(ParameterSetName='Evaluate')][switch]$Evaluate,
    [string]$TargetDate,
    [switch]$RefreshCanonical
)
$ErrorActionPreference = 'Stop'
$repo = 'D:\us-tech-quant'
$python = 'D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe'
$script = Join-Path $repo 'scripts\v22\a2_ng8_risk_r2_true_forward_chain_r1.py'
if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $script)) { throw 'FORWARD_RUNTIME_MISSING' }
$mode = if ($Execute) { '--execute' } elseif ($Evaluate) { '--evaluate' } else { '--dry-run' }
$arguments = @($script, $mode)
if ($TargetDate) { $arguments += @('--target-date', $TargetDate) }
if ($RefreshCanonical) { $arguments += '--refresh-canonical' }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "TRUE_FORWARD_CHAIN_FAILED:$LASTEXITCODE" }
