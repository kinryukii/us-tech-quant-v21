"""Audit existing price/feature identity; never fit or change source data."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
records = []
for period in ("pre", "test"):
    panel_path = ROOT / "data" / ("pre_panel.parquet" if period == "pre" else "test_panel.parquet")
    cols = ["signal_date", "ticker", "ret_1d", "new_buy_eligible"]
    if period == "pre":
        cols += ["close", "y_next_open", "label_available", "label_price_warning"]
    panel = pd.read_parquet(panel_path, columns=cols)
    price_cols = ["trade_date", "ticker", "close"]
    if period == "test":
        price_cols += ["price_quality_warning"]
    prices = pd.read_parquet(ROOT / "data" / ("pre_prices.parquet" if period == "pre" else "test_prices.parquet"), columns=price_cols)
    assert not prices.duplicated(["ticker", "trade_date"]).any()
    prices = prices.sort_values(["ticker", "trade_date"])
    prices["previous_date"] = prices.groupby("ticker").trade_date.shift()
    prices["bound_close_return"] = prices.close / prices.groupby("ticker").close.shift() - 1
    if period == "test":
        prices["both_prices_qualified"] = ~prices.price_quality_warning & ~prices.groupby("ticker").price_quality_warning.shift().fillna(True).astype(bool)
    else:
        prices["both_prices_qualified"] = True
    sessions = sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique())
    previous_session = {pd.Timestamp(sessions[i]): pd.Timestamp(sessions[i-1]) for i in range(1, len(sessions))}
    prices = prices.rename(columns={"trade_date": "signal_date", "close": "bound_close"})
    merged = panel.merge(prices[["signal_date", "ticker", "bound_close", "bound_close_return", "previous_date", "both_prices_qualified"]],
                         on=["signal_date", "ticker"], how="left", validate="one_to_one")
    valid = np.isfinite(merged.bound_close_return) & merged.previous_date.eq(merged.signal_date.map(previous_session))
    for year, part in merged.groupby(merged.signal_date.dt.year):
        ok = valid.loc[part.index]
        error = np.abs(part.loc[ok, "ret_1d"] - part.loc[ok, "bound_close_return"])
        record = {"year": int(year), "period": period, "panel_rows": len(part), "return_comparable_rows": int(ok.sum()),
                  "return_mismatch_over_1e_minus7": int((error > 1e-7).sum()),
                  "maximum_return_abs_error": float(error.max()),
                  "median_return_abs_error": float(error.median()),
                  "both_prices_qualified_rows": int((ok & part.both_prices_qualified).sum())}
        trusted_error = np.abs(part.loc[ok & part.both_prices_qualified, "ret_1d"] - part.loc[ok & part.both_prices_qualified, "bound_close_return"])
        record["qualified_pair_mismatch_over_1e_minus7"] = int((trusted_error > 1e-7).sum())
        if period == "pre":
            close_error = np.abs(part.close - part.bound_close)
            labels = part.loc[part.label_available & ~part.label_price_warning]
            date_means = labels.groupby("signal_date").y_next_open.mean()
            record.update({"close_mismatch_over_1e_minus7": int((close_error > 1e-7).sum()),
                           "available_nonwarning_labels": len(labels),
                           "date_equal_label_mean_bp": float(date_means.mean() * 10000),
                           "label_row_mean_bp": float(labels.y_next_open.mean() * 10000)})
        mismatched = part.loc[ok & (np.abs(part.ret_1d - part.bound_close_return) > 1e-7)].copy()
        record["example_mismatches"] = mismatched[["signal_date", "ticker", "ret_1d", "bound_close_return", "both_prices_qualified"]].head(5).to_dict("records")
        records.append(record)

result = {"status": "READ_ONLY_POSTHOC_PRICE_FEATURE_ALIGNMENT", "fit_calls": 0, "replay_calls": 0,
          "scope": "Compare stored ret_1d with returns of frozen bound close prices on consecutive master sessions. Does not certify real shareholder returns or vendor arrival times.",
          "records": records}
path = ROOT / "results" / "diagnostics" / "PRICE_FEATURE_ALIGNMENT_READONLY_20260929.json"
path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
