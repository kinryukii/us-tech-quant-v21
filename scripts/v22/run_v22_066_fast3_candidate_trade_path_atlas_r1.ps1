[CmdletBinding()]param([switch]$Execute)
$ErrorActionPreference='Stop';if(-not $Execute){throw 'The -Execute flag is required.'};$repo=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path;Set-Location $repo
& "$repo\.venv\Scripts\python.exe" "$repo\scripts\v22\v22_066_fast3_candidate_trade_path_atlas_r1.py" --execute;exit $LASTEXITCODE
