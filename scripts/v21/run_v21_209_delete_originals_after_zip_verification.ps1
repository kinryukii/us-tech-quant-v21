param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$ApprovalPhrase = ""
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path $RepoRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $Python = $VenvPython
} else {
    $Python = "python"
}

$ArgsList = @(
    (Join-Path $Root "scripts\v21\v21_209_delete_originals_after_zip_verification.py"),
    "--repo-root",
    $Root
)
if ($ApprovalPhrase -ne "") {
    $ArgsList += @("--approval-phrase", $ApprovalPhrase)
}

& $Python @ArgsList
exit $LASTEXITCODE
