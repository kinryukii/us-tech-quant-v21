Set-StrictMode -Version Latest

function Get-Fast3CanonicalPath([string]$PathValue) {
    return [System.IO.Path]::GetFullPath($PathValue).TrimEnd('\\')
}

function Test-Fast3SamePath([string]$Left, [string]$Right) {
    return [string]::Equals((Get-Fast3CanonicalPath $Left), (Get-Fast3CanonicalPath $Right), [System.StringComparison]::OrdinalIgnoreCase)
}

function Test-Fast3PathEntryExists([string]$PathValue) {
    # Enumerate the parent rather than following the child, so a dangling reparse
    # point is still treated as a prohibited reintroduction.
    $parent = [System.IO.Path]::GetDirectoryName($PathValue)
    $leaf = [System.IO.Path]::GetFileName($PathValue)
    $entry = Get-ChildItem -LiteralPath $parent -Force -ErrorAction Stop |
        Where-Object { [string]::Equals($_.Name, $leaf, [System.StringComparison]::Ordinal) } |
        Select-Object -First 1
    return $null -ne $entry
}

function Resolve-Fast3StorageContract {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$ExternalResultsRoot,
        [Parameter(Mandatory = $true)][string]$CacheRoot
    )

    $approvedResultsRoot = 'D:\us-tech-quant-results'
    $approvedCacheRoot = 'D:\us-tech-quant-cache'
    $legacyCompatibilityRoot = Join-Path $approvedResultsRoot 'runtime\local_results'
    $retiredLegacyLogicalPath = 'D:\us-tech-quant\.local_results'
    $configuredResultsRoot = Get-Fast3CanonicalPath $ExternalResultsRoot
    $configuredPath = $ExternalResultsRoot
    $resolvedPath = $configuredResultsRoot
    $classification = 'APPROVED_EXTERNAL_RESULTS_ROOT'
    $physicalLinkExists = $false
    $approvalReason = 'approved external results root'

    # This is intentionally an ordinal string comparison, before path normalization.
    # Only the historical spelling is a permitted alias; case, separators, child paths,
    # and normalization tricks such as `..` must fail closed.
    $isExactRetiredLegacyAlias = [string]::Equals(
        $ExternalResultsRoot,
        $retiredLegacyLogicalPath,
        [System.StringComparison]::Ordinal
    )
    if ($isExactRetiredLegacyAlias) {
        if (Test-Fast3PathEntryExists $retiredLegacyLogicalPath) {
            throw "Retired legacy path has been reintroduced and is forbidden: $retiredLegacyLogicalPath"
        }
        $configuredResultsRoot = $approvedResultsRoot
        $resolvedPath = $legacyCompatibilityRoot
        $classification = 'LEGACY_PATH_ALIAS_AFTER_JUNCTION_REMOVAL'
        $approvalReason = 'exact retired legacy path mapped to approved external runtime target'
    }
    elseif (-not (Test-Fast3SamePath $configuredResultsRoot $approvedResultsRoot)) {
        $item = Get-Item -LiteralPath $configuredResultsRoot -Force -ErrorAction Stop
        $target = @($item.Target | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) | Select-Object -First 1
        if ($null -eq $target -or -not (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
            throw "ExternalResultsRoot is not the approved results root or an approved compatibility ReparsePoint: $configuredResultsRoot"
        }
        $targetPath = Get-Fast3CanonicalPath $target
        if (-not (Test-Fast3SamePath $targetPath $legacyCompatibilityRoot)) {
            throw "Compatibility ReparsePoint target is not approved: $targetPath"
        }
        $configuredResultsRoot = $approvedResultsRoot
        $resolvedPath = $configuredResultsRoot
        $physicalLinkExists = $true
        $classification = 'REJECTED_LEGACY_COMPATIBILITY_REPARSE_POINT'
        $approvalReason = 'legacy compatibility ReparsePoints are retired and forbidden'
        throw "Legacy compatibility ReparsePoints are retired and forbidden: $ExternalResultsRoot"
    }
    if (-not (Test-Fast3SamePath $CacheRoot $approvedCacheRoot)) {
        throw "CacheRoot must be the approved external cache root: $approvedCacheRoot"
    }
    if (Test-Fast3SamePath $configuredResultsRoot $RepoRoot) {
        throw "Results root must not be the repository root."
    }

    return [pscustomobject]@{
        ResultsRoot = $configuredResultsRoot
        RuntimeRoot = Join-Path $configuredResultsRoot 'runtime'
        ScratchRoot = Join-Path $configuredResultsRoot 'scratch'
        FrozenRoot = Join-Path $configuredResultsRoot 'frozen'
        ArchiveRoot = Join-Path $configuredResultsRoot 'archive'
        CacheRoot = Get-Fast3CanonicalPath $CacheRoot
        LegacyCompatibilityRoot = $legacyCompatibilityRoot
        configured_path = $configuredPath
        resolved_path = $resolvedPath
        classification = $classification
        physical_link_exists = $physicalLinkExists
        approval_reason = $approvalReason
    }
}
