$ErrorActionPreference = "Stop"

python scripts/v21/v21_174_r1b_manual_dram_price_ingestion_and_watchlist_trade_anchor.py
python -m pytest scripts/v21/test_v21_174_r1b_manual_dram_price_ingestion_and_watchlist_trade_anchor.py -q

$outDir = "outputs/v21/V21.174_R1B_MANUAL_DRAM_PRICE_INGESTION_AND_WATCHLIST_TRADE_ANCHOR"
Get-Content "$outDir/V21.174_R1B_readable_report.txt"
Get-Content "$outDir/V21.174_R1B_summary.json"
