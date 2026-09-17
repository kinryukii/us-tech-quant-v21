[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')]
    [string]$TargetDate,

    [Parameter(Mandatory = $true)]
    [ValidateSet('Preflight', 'DryRun', 'ValidateFixture', 'Production', 'Resume', 'Status', 'ValidateHistoryChain')]
    [string]$Mode,

    [string]$WorkspaceRoot,
    [string]$Fixture,
    [string]$ReadinessJson,
    [string]$ReadinessSha256,
    [string]$StatusOutput
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$PythonExe = 'D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe'
$Runner = Join-Path $PSScriptRoot 'a2_forward_shadow_unified_r1.py'

if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Canonical Python runtime not found: $PythonExe"
}
if (-not (Test-Path -LiteralPath $Runner -PathType Leaf)) {
    throw "Unified runner not found: $Runner"
}

$ModeMap = @{
    Preflight = 'preflight'
    DryRun = 'dry-run'
    ValidateFixture = 'validate-fixture'
    Production = 'production'
    Resume = 'resume'
    Status = 'status'
    ValidateHistoryChain = 'validate-history-chain'
}
$Arguments = @($Runner, $ModeMap[$Mode], '--target-date', $TargetDate)
if ($WorkspaceRoot) { $Arguments += @('--workspace-root', $WorkspaceRoot) }
if ($Fixture) { $Arguments += @('--fixture', $Fixture) }
if ($ReadinessJson) { $Arguments += @('--readiness-json', $ReadinessJson) }
if ($ReadinessSha256) { $Arguments += @('--readiness-sha256', $ReadinessSha256) }
if ($StatusOutput) { $Arguments += @('--status-output', $StatusOutput) }

& $PythonExe @Arguments
exit $LASTEXITCODE
