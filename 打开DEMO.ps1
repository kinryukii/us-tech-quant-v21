[CmdletBinding()]
param([ValidateRange(1, 65535)][int]$Port = 8506)

$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'apps/demo_console/start.ps1') -Port $Port
