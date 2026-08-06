[CmdletBinding()]
param(
    [string]$CanonicalRoot = "D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical",
    [string]$ResultsRoot = "D:\us-tech-quant-results"
)

# This tool is deliberately separate from the research launcher.
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "ADMINISTRATOR_REQUIRED"
}
$item = Get-Item -LiteralPath $CanonicalRoot -Force
if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "CANONICAL_ROOT_INVALID_OR_REPARSE" }
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$out = Join-Path $ResultsRoot "frozen\fast3\acl_hardening\$stamp"
New-Item -ItemType Directory -Force -Path $out | Out-Null
$before = Get-Acl -LiteralPath $CanonicalRoot
$backup = Join-Path $out "canonical_acl_before.sddl.txt"
$before.Sddl | Set-Content -LiteralPath $backup -Encoding UTF8
$beforeHash = (Get-FileHash -LiteralPath $backup -Algorithm SHA256).Hash.ToLowerInvariant()
$contentBefore = (Get-ChildItem -LiteralPath $CanonicalRoot -File -Recurse | Get-FileHash -Algorithm SHA256 | ForEach-Object { $_.Hash } | Sort-Object | Out-String)
$contentBeforeHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($contentBefore))).ToLowerInvariant()
$restore = Join-Path $out "restore_fast3_canonical_acl_r1.ps1"
@("Set-StrictMode -Version Latest", "`$acl = New-Object System.Security.AccessControl.DirectorySecurity", "`$acl.SetSecurityDescriptorSddlForm((Get-Content -LiteralPath '$backup' -Raw))", "Set-Acl -LiteralPath '$CanonicalRoot' -AclObject `$acl") | Set-Content -LiteralPath $restore -Encoding UTF8
$denyRights = [System.Security.AccessControl.FileSystemRights]::WriteData -bor [System.Security.AccessControl.FileSystemRights]::AppendData -bor [System.Security.AccessControl.FileSystemRights]::WriteAttributes -bor [System.Security.AccessControl.FileSystemRights]::WriteExtendedAttributes -bor [System.Security.AccessControl.FileSystemRights]::Delete -bor [System.Security.AccessControl.FileSystemRights]::WriteDac -bor [System.Security.AccessControl.FileSystemRights]::TakeOwnership
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule("Authenticated Users",$denyRights,"ContainerInherit,ObjectInherit","None","Deny")
[void]$before.AddAccessRule($rule); Set-Acl -LiteralPath $CanonicalRoot -AclObject $before
$after = Get-Acl -LiteralPath $CanonicalRoot
$afterPath = Join-Path $out "canonical_acl_after.sddl.txt"; $after.Sddl | Set-Content -LiteralPath $afterPath -Encoding UTF8
$contentAfter = (Get-ChildItem -LiteralPath $CanonicalRoot -File -Recurse | Get-FileHash -Algorithm SHA256 | ForEach-Object { $_.Hash } | Sort-Object | Out-String)
$contentAfterHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($contentAfter))).ToLowerInvariant()
if ($contentBeforeHash -ne $contentAfterHash) { & $restore; throw "CONTENT_HASH_CHANGED_ROLLED_BACK" }
[ordered]@{ACL_HARDENING_PERFORMED=$true;ACL_BACKUP_PATH=$backup;ACL_BEFORE_SDDL_SHA256=$beforeHash;ACL_AFTER_SDDL_SHA256=(Get-FileHash $afterPath -Algorithm SHA256).Hash.ToLowerInvariant();CANONICAL_CONTENT_HASH_UNCHANGED=$true;ROLLBACK_SCRIPT_PATH=$restore;FINAL_HARDENING_DECISION="PASS"} | ConvertTo-Json | Set-Content (Join-Path $out "ACL_HARDENING_MANIFEST.json") -Encoding UTF8
