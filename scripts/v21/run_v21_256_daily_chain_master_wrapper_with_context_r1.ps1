param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$OutputDir = "",
    [switch]$AuditOnly,
    [switch]$Execute
)
$ErrorActionPreference = "Stop"
Set-Location $RepoRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "scripts\v21\v21_256_daily_chain_master_wrapper_with_context_r1.py"
$RunMode = "AuditOnly"
if ($Execute) { $RunMode = "Execute" }
$OutRoot = Join-Path $RepoRoot "outputs\v21\V21.256_DAILY_CHAIN_MASTER_WRAPPER_WITH_CONTEXT_R1"
New-Item -ItemType Directory -Force -Path $OutRoot | Out-Null
$ArgsList = @($Script, "--repo-root", $RepoRoot, "--run-mode", $RunMode)
if ($OutputDir) { $ArgsList += @("--output-dir", $OutputDir) }
& $Python @ArgsList *> (Join-Path $OutRoot "v21_256_wrapper_stdout.log")
$ExitCode = $LASTEXITCODE
Get-Content -Path (Join-Path $OutRoot "v21_256_wrapper_stdout.log")
exit $ExitCode
