param([switch]$Execute)

$r = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$exclude = Join-Path $r '.git\info\exclude'
if (-not (Test-Path -LiteralPath $exclude -PathType Leaf)) { New-Item -ItemType File -Path $exclude -Force | Out-Null }
if (-not (Select-String -LiteralPath $exclude -SimpleMatch -Quiet -Pattern '.local_results/' -ErrorAction SilentlyContinue)) { Add-Content -LiteralPath $exclude -Value '.local_results/' }
$p = Join-Path $r '.venv\Scripts\python.exe'
$m = Join-Path $r 'scripts\v22\v22_069a_fast_research_contract_r1.py'
$t = Join-Path $r 'scripts\v22\test_v22_069a_fast_research_contract_r1.py'
& $p -m py_compile $m
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $p -m pytest $t -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($Execute) {
    & $p $m --execute
    $pythonExit = $LASTEXITCODE
    Write-Output "PYTHON_PROCESS_EXIT_CODE=$pythonExit"
    if ($pythonExit -ne 0) { Write-Output "RUNNER_EXIT_CODE=$pythonExit"; exit $pythonExit }
    $summaryPath = Join-Path $r '.local_results\v22\V22.069A_FAST_RESEARCH_CONTRACT_R1\v22_069a_fast_summary.json'
    if (-not (Test-Path -LiteralPath $summaryPath -PathType Leaf)) { Write-Output 'RUNNER_EXIT_CODE=1'; exit 1 }
    $summary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
    if ([string]$summary.final_status -ne 'PASS') { Write-Output 'RUNNER_EXIT_CODE=1'; exit 1 }
    Write-Output 'RUNNER_EXIT_CODE=0'
    exit 0
}
