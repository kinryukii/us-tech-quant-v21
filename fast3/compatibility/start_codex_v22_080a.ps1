[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = "D:\us-tech-quant"
$promptPath = Join-Path $repoRoot "fast3\docs\legacy\directives\repository_root\CODEX_AUTOPILOT_PROMPT.txt"

if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    throw "Codex CLI not found in PATH."
}
if (-not (Test-Path -LiteralPath $promptPath)) {
    throw "Autopilot prompt not found: $promptPath"
}

Set-Location -LiteralPath $repoRoot

Write-Host "========== Git status before Codex =========="
git status --short

Write-Host ""
Write-Host "Starting Codex in: $repoRoot"
Write-Host "When prompted, trust this repository."
Write-Host "Paste the contents of CODEX_AUTOPILOT_PROMPT.txt as the first task."
Write-Host ""

codex
