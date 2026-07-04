param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$ApprovalPhrase = ""
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path $RepoRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) { $Python = $VenvPython } else { $Python = "python" }

$ArgsList = @(
    (Join-Path $Root "scripts\v21\v21_219_delete_archive_and_historical_outputs_after_approval.py"),
    "--repo-root",
    $Root
)
if ($ApprovalPhrase -ne "") {
    $ArgsList += @("--approval-phrase", $ApprovalPhrase)
}

& $Python @ArgsList
exit $LASTEXITCODE
