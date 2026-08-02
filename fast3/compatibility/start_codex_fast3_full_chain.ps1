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
    throw "Prompt not found: $promptPath"
}

Set-Location -LiteralPath $repoRoot

Write-Host "========== FAST3 full-chain Codex startup =========="
Write-Host "Repository: $repoRoot"
Write-Host "Prompt:     $promptPath"
Write-Host ""
Write-Host "The full-chain prompt has been copied to the clipboard."
Write-Host "Paste it into Codex and send it once."
Write-Host ""

Get-Content -LiteralPath $promptPath -Raw -Encoding UTF8 | Set-Clipboard
codex
