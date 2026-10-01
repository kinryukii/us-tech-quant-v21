$ErrorActionPreference = 'Stop'
$target = Join-Path $PSScriptRoot 'raw_second'
New-Item -ItemType Directory -Path $target -Force | Out-Null
$sources = @(
  @{ Code='GEV'; Url='https://www.gevernova.com/news/press-releases/ge-vernova-declares-increased-first-quarter-2026-dividend-increases-buyback-authorization'; File='GEV_2025_12_09_DIVIDEND.html' },
  @{ Code='JPM'; Url='https://jpmorganchaseco.gcs-web.com/ir/shareholder-information/dividend-history?field_nir_div_year_value=1977'; File='JPM_DIVIDEND_HISTORY.html' },
  @{ Code='JPM'; Url='https://www.jpmorganchase.com/ir/news/2025/jpmc-declares-common-stock-dividend-12-9'; File='JPM_2025_12_09_DIVIDEND.html' },
  @{ Code='MA'; Url='https://investor.mastercard.com/investor-news/investor-news-details/2025/Mastercard-Board-of-Directors-Announces-Quarterly-Dividend-and-14-Billion-Share-Repurchase-Program/default.aspx'; File='MA_2025_12_09_DIVIDEND.html' },
  @{ Code='MRVL'; Url='https://investor.marvell.com/sec-filings/all-sec-filings/content/0001628280-25-056774/marvelltechnologyinc_divid.htm'; File='MRVL_2025_12_12_SEC_EX99_1.html' },
  @{ Code='ORCL'; Url='https://investor.oracle.com/investor-news/news-details/2025/Oracle-Announces-Fiscal-Year-2026-Second-Quarter-Financial-Results/'; File='ORCL_2025_12_10_DIVIDEND.html' }
)
$receipts = @()
foreach ($source in $sources) {
  $path = Join-Path $target $source.File
  $record = [ordered]@{ code=$source.Code; url=$source.Url; path=$path; fetched_utc=$null; result=$null; sha256=$null; bytes=$null; error=$null }
  try {
    if (Test-Path -LiteralPath $path) { throw 'Target exists; refusing to overwrite' }
    Invoke-WebRequest -Uri $source.Url -OutFile $path -TimeoutSec 15 | Out-Null
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
$receiptPath = Join-Path $PSScriptRoot 'SECOND_TRANCHE_PRIMARY_FETCH_RECEIPTS.json'
if (Test-Path -LiteralPath $receiptPath) { throw 'Receipt target exists; refusing to overwrite' }
$receipts | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $receiptPath -Encoding utf8
