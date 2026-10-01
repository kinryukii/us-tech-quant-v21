"""Preserve inherited label warnings as diagnostics; never filter panel rows."""
from pathlib import Path
import json
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import panel
import pandas as pd


def main():
    out = ROOT / "panel_artifacts"
    source = pd.read_parquet(panel.SOURCE, columns=["signal_date", "ticker", "execution_date",
        "label_end_date", "y_next_open", "label_available", "label_price_warning"])
    source = source.loc[source.signal_date.dt.year.isin([2024, 2025])].copy()
    flagged = source.loc[source.label_price_warning].copy()
    flagged["warning_reason"] = "original source supplies boolean only; reason not separately provided"
    flagged.to_parquet(out / "label_warning_source_keys.parquet", index=False)
    records = []
    for year in [2024, 2025]:
        keys_path = out / f"panel_keys_{year}.parquet"
        if not keys_path.exists():
            continue
        keys = pd.read_parquet(keys_path, columns=["key_id", "behavior_path", "signal_date", "ticker", "label_end_date", "y_next_open"])
        before = len(keys)
        joined = keys.merge(source[["signal_date", "ticker", "label_price_warning"]],
                            on=["signal_date", "ticker"], how="left", validate="many_to_one")
        assert len(joined) == before and joined.label_price_warning.notna().all()
        p = out / f"warning_keys_{year}.parquet"
        joined.to_parquet(p, index=False)
        records.append(dict(year=year, sample_stock_dates=before,
            sample_warning_stock_dates=int(joined.label_price_warning.sum()),
            unique_sample_warning_events=int(joined.loc[joined.label_price_warning,["signal_date","ticker"]].drop_duplicates().shape[0]),
            source_warning_events=int(flagged.signal_date.dt.year.eq(year).sum()),
            path=str(p), sha256=panel.sha(p)))
    receipt = dict(status="PASS" if len(records) == 2 else "PARTIAL_WAITING_FOR_PANEL_2025", 
        source_path=str(panel.SOURCE), source_sha256=panel.sha(panel.SOURCE),
        source_warning_keys_path=str(out/"label_warning_source_keys.parquet"),
        source_warning_keys_sha256=panel.sha(out/"label_warning_source_keys.parquet"), years=records,
        policy="inherited warning preserved; no filtering, no state/candidate/target changes; clipped training and raw evaluation unchanged",
        diagnostic_only=True, source_reason_field_available=False,
        note="Original pre2026 replay price file has only ticker/trade_date/open/close; label_price_warning is not a new execution restriction.")
    panel.write(out / "LABEL_WARNING_RECEIPT.json", receipt)
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
