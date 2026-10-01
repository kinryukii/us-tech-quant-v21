"""Rebuild frozen predictions from source prefixes at six fixed signal dates."""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

AUDIT = Path(__file__).resolve().parent
ROOT = AUDIT.parent
sys.path.insert(0, str(ROOT))
import batch2026
import prepare

DATES = ["2026-01-05", "2026-01-06", "2026-02-25", "2026-03-16", "2026-06-15", "2026-08-10"]


def main():
    if (AUDIT / "prefix_features.csv").exists():
        raise RuntimeError("ALREADY_RUN")
    saved = pd.read_parquet(ROOT / "test2026" / "predictions.parquet")
    model = joblib.load(ROOT / "models" / "hgb_2026092501.joblib")
    rows = []
    for date_string in DATES:
        date = pd.Timestamp(date_string)
        rank = ds.dataset(batch2026.SOURCE / "top40.parquet", format="parquet").to_table(
            filter=ds.field("target_date") == date_string).to_pandas()
        assert len(rank) == 40
        rank = rank.rename(columns={"score": "raw_score", "rank": "raw_rank"})
        rank["signal_date"] = date
        rank["raw_rank_strength"] = 1 - (rank.raw_rank.astype(float)-1)/39
        rank["raw_score_z"] = (rank.raw_score-rank.raw_score.mean()) / rank.raw_score.std(ddof=0)
        historical = ds.dataset(batch2026.SOURCE / "inference_features.parquet", format="parquet").to_table(
            columns=["trade_date", "ticker", *prepare.BASE_FEATURES],
            filter=ds.field("trade_date") <= date.to_pydatetime()).to_pandas()
        historical["trade_date"] = pd.to_datetime(historical.trade_date)
        historical = historical.sort_values(["ticker", "trade_date"])
        for k in range(10):
            historical[f"lag_ret_{k:02d}"] = historical.groupby("ticker", sort=False).ret_1d.shift(k)
        rebuilt = rank.merge(historical.loc[historical.trade_date.eq(date)].rename(
            columns={"trade_date": "signal_date"}), on=["signal_date", "ticker"],
            how="left", validate="one_to_one")
        persisted = saved.loc[saved.signal_date.eq(date)]
        a = rebuilt.set_index("ticker").sort_index()
        b = persisted.set_index("ticker").sort_index()
        assert a.index.equals(b.index)
        numeric = ["raw_rank_strength", "raw_score_z", *prepare.BASE_FEATURES,
                   *(f"lag_ret_{k:02d}" for k in range(10))]
        difference = np.abs(a[numeric].to_numpy(float) - b[numeric].to_numpy(float))
        prediction = model.predict(a[prepare.FEATURES])
        rows.append({"signal_date": date_string, "tickers": len(a),
                     "feature_max_absdiff": float(np.nanmax(difference)),
                     "missing_pattern_equal": bool(np.array_equal(np.isnan(a[numeric]), np.isnan(b[numeric]))),
                     "hgb_prediction_max_absdiff": float(np.max(abs(prediction-b.pred_hgb.to_numpy(float))))})
    table = pd.DataFrame(rows)
    table.to_csv(AUDIT / "prefix_features.csv", index=False)
    print(table.to_string(index=False))


if __name__ == "__main__":
    main()
