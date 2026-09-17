[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')]
    [string]$TargetDate,
    [string]$OutputRoot,
    [string]$AsOfTimestamp,
    [string]$Timezone = 'Asia/Tokyo',
    [string]$ComponentInputsJson
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$PythonExe = 'D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe'
$Generator = Join-Path $PSScriptRoot 'a2_forward_shadow_readiness_r1.py'
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw "Canonical Python runtime not found: $PythonExe" }
if (-not (Test-Path -LiteralPath $Generator -PathType Leaf)) { throw "Readiness generator not found: $Generator" }

$Arguments = @($Generator, '--target-date', $TargetDate)
if ($OutputRoot) { $Arguments += @('--output-root', $OutputRoot) }
if ($AsOfTimestamp) { $Arguments += @('--as-of-timestamp', $AsOfTimestamp) }
if ($Timezone) { $Arguments += @('--timezone', $Timezone) }
if ($ComponentInputsJson) { $Arguments += @('--component-inputs-json', $ComponentInputsJson) }
& $PythonExe @Arguments
exit $LASTEXITCODE
