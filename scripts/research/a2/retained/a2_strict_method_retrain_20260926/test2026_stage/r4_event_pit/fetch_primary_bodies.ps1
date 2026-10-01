$ErrorActionPreference = 'Stop'
$target = Join-Path $PSScriptRoot 'raw'
New-Item -ItemType Directory -Path $target -Force | Out-Null
$sources = @(
  @{ Code='APD'; Url='https://investors.airproducts.com/static-files/c828aa86-b3a8-4dfb-97b9-dee499c4d136'; File='APD_2025_ANNUAL_REPORT.pdf' },
  @{ Code='FERG'; Url='https://www.sec.gov/Archives/edgar/data/2011641/000201164125000057/exhibit991pressreleaseocto.htm'; File='FERG_2025_12_09_SEC_EX99_1.html' },
  @{ Code='ROP'; Url='https://investors.ropertech.com/stock-information/dividends-splits'; File='ROP_DIVIDEND_HISTORY.html' },
  @{ Code='PGR'; Url='https://investors.progressive.com/financials/financial-news-releases/news-details/2025/Progressive-Announces-Dividend-Information-And-2026-Annual-Meeting-Record-Date/default.aspx'; File='PGR_2025_12_08_DIVIDEND.html' }
)
$receipts = @()
foreach ($source in $sources) {
  $path = Join-Path $target $source.File
  $record = [ordered]@{ code=$source.Code; url=$source.Url; path=$path; fetched_utc=$null; result=$null; sha256=$null; bytes=$null; error=$null }
  try {
    if (Test-Path -LiteralPath $path) { throw "Target already exists; refusing to overwrite" }
    Invoke-WebRequest -Uri $source.Url -OutFile $path -TimeoutSec 25 | Out-Null
    $record.fetched_utc = (Get-Date).ToUniversalTime().ToString('o')
    $record.sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    $record.bytes = (Get-Item -LiteralPath $path).Length
    $record.result = 'SAVED'
  } catch {
    $record.fetched_utc = (Get-Date).ToUniversalTime().ToString('o')
    $record.result = 'FAILED'
    $record.error = $_.Exception.Message
    if ((Test-Path -LiteralPath $path) -and ((Get-Item -LiteralPath $path).Length -eq 0)) { Remove-Item -LiteralPath $path }
  }
  $receipts += [pscustomobject]$record
  Write-Output ([pscustomobject]$record | ConvertTo-Json -Compress)
}
$receiptPath = Join-Path $PSScriptRoot 'PRIMARY_BODY_FETCH_RETRY2_RECEIPTS.json'
if (Test-Path -LiteralPath $receiptPath) { throw "Receipt target already exists; refusing to overwrite" }
$receipts | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $receiptPath -Encoding utf8
