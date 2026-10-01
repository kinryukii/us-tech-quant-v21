"""Targeted QQQ overlap check; no strategy returns."""
import csv
from pathlib import Path

import pandas as pd

ROOT = Path("D:/us-tech-quant-data/canonical/moomoo_ohlcv/snapshot_id=data_layer_20260911_99642e55d6185fe2402b")
DATES = {"2025-12-31", "2026-01-02", "2026-07-14"}

def main():
    for kind in ("raw", "qfq"):
        source = ROOT / f"canonical_moomoo_ohlcv_daily_{kind}.csv"
        rows = {}
        with source.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                if row["ticker"] == "QQQ" and row["date"] in DATES:
                    rows[row["date"]] = {key: float(row[key]) for key in ("open", "close")}
        print(kind, rows)
    for year in (2025, 2026):
        source = Path(f"D:/us-tech-quant-data/moomoo/source/prices_qfq/year={year}/prices.parquet")
        frame = pd.read_parquet(source, columns=["ticker", "trade_date", "open", "close"])
        frame["trade_date"] = pd.to_datetime(frame.trade_date)
        print(f"old_{year}", frame.loc[frame.ticker.eq("QQQ") & frame.trade_date.isin(pd.to_datetime(list(DATES)))].to_dict("records"))

if __name__ == "__main__":
    main()
