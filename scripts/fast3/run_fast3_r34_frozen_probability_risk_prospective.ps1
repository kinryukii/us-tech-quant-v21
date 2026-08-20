[CmdletBinding()]
param(
    [switch]$Execute
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $Execute) {
    throw 'Use -Execute to run the frozen R34 prospective entrypoint.'
}

$repoRoot = 'D:\us-tech-quant'
$runner = Join-Path $repoRoot 'fast3\scripts\run\fast3_r34_frozen_probability_risk_prospective.py'
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "R34 runner not found: $runner"
}

Push-Location $repoRoot
try {
    & python $runner --execute
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
