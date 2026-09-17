[CmdletBinding()]
param([string]$RepoRoot = "D:\us-tech-quant", [string]$TaskPrefix = "US-Tech-Quant-V22.047-R1E")
$ErrorActionPreference = "Stop"
. (Join-Path $RepoRoot "scripts\common\storage_paths.ps1")
$Storage = Get-UstqStoragePaths -RepoRoot $RepoRoot
$Python = $Storage.python_exe
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "Python not found: $Python" }
$Main = Join-Path $RepoRoot "scripts\v22\v22_047_r1e_windows_service_hardening.py"
& $Python $Main status --repo-root $RepoRoot
$Code = $LASTEXITCODE
Get-ScheduledTask -TaskName "$TaskPrefix-*" -ErrorAction SilentlyContinue | Select-Object TaskName,State | Format-Table -AutoSize
exit $Code

