[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$LegacyPanelPath,
    [string]$StockDataRoot = 'D:\us-tech-quant-data\stocks',
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [ValidateSet(1, 5, 10, 20)][int]$Horizon = 1,
    [int]$ChunkSize = 200000,
    [switch]$Resume,
    [switch]$Execute
)

$python = 'D:\us-tech-quant\.venv\Scripts\python.exe'
$script = Join-Path $PSScriptRoot 'compare_legacy_forward_overlap_r1.py'
$arguments = @($script, '--legacy-panel-path', $LegacyPanelPath, '--stock-data-root', $StockDataRoot,
    '--output-dir', $OutputDir, '--horizon', $Horizon, '--chunk-size', $ChunkSize)
if ($Resume) { $arguments += '--resume' }
if (-not $Execute) {
    Write-Output ('WhatIf: ' + $python + ' ' + ($arguments -join ' '))
    exit 0
}
& $python @arguments
exit $LASTEXITCODE
