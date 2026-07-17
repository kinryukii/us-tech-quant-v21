[CmdletBinding()]
param([string]$RepoRoot = "D:\us-tech-quant", [string]$TaskPrefix = "US-Tech-Quant-V22.047-R1E")
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Main = Join-Path $RepoRoot "scripts\v22\v22_047_r1e_windows_service_hardening.py"
& $Python $Main status --repo-root $RepoRoot
$Code = $LASTEXITCODE
Get-ScheduledTask -TaskName "$TaskPrefix-*" -ErrorAction SilentlyContinue | Select-Object TaskName,State | Format-Table -AutoSize
exit $Code

