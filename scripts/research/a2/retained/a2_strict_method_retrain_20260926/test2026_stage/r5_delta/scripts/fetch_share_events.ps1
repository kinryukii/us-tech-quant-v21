$base = Join-Path $PSScriptRoot 'raw_share_events'
New-Item -ItemType Directory -Path $base -Force | Out-Null
$targets = @(
    @('BKNG_2026_02_split.pdf','https://www.bookingholdings.com/wp-content/uploads/2026/02/Q4-25-BKNG-Earnings-Release.pdf'),
    @('CVNA_2026_proxy.pdf','https://investors.carvana.com/~/media/Files/C/Carvana-IR/documents/carvana-co-2026-proxy-statement-definitive.pdf'),
    @('KLAC_2026_05_07_ex991.html','https://ir.kla.com/sec-filings/all-sec-filings/content/0001193125-26-212093/d116682dex991.htm'),
    @('SLMT_2026_05_12_nasdaq.html','https://m.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-318'),
    @('CRWD_2026_06_split.pdf','https://ir.crowdstrike.com/static-files/f774ef12-cf94-48bf-ace2-c7f3dcf8ec97'),
    @('DD_2026_05_26_issuer.html','https://www.investors.dupont.com/news-and-media/press-release-details/2026/DuPont-Announces-Reverse-Stock-Split-and-Reaffirms-2026-Financial-Guidance/default.aspx'),
    @('BYND_2026_08_nasdaq.html','https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-568'),
    @('HON_2026_06_05_issuer.html','https://www.honeywell.com/us/en/press/2026/06/honeywell-board-of-directors-sets-record-date-and-announces-expected-timing-for-spin-off-of-honeywell-aerospace-and-honeywell-reverse-stock-split')
)
$receipts = @()
foreach ($item in $targets) {
    $path = Join-Path $base $item[0]
    $row = @{name=$item[0];url=$item[1];fetched_utc=(Get-Date).ToUniversalTime().ToString('o')}
    if (Test-Path -LiteralPath $path) { $row.result='EXISTING_NO_OVERWRITE' }
    else {
        try {
            $client = [System.Net.Http.HttpClient]::new()
            $client.Timeout = [TimeSpan]::FromSeconds(12)
            $bytes = $client.GetByteArrayAsync($item[1]).GetAwaiter().GetResult()
            [System.IO.File]::WriteAllBytes($path,$bytes)
            $row.result='SAVED'
            $client.Dispose()
        } catch { $row.result='FAILED'; $row.error=$_.Exception.Message }
    }
    if (Test-Path -LiteralPath $path) { $row.bytes=(Get-Item -LiteralPath $path).Length; $row.sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash }
    $receipts += $row
}
$receipts | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'SHARE_EVENT_PRIMARY_FETCH_RECEIPTS.json') -Encoding utf8
$receipts | ConvertTo-Json -Depth 5
