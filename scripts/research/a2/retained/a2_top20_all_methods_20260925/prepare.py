"""Mechanical pre-2026-only panel preparation; no 2026 values enter fit code."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent
PREVIOUS = ROOT.parent / "a2_top20_action_nn_20260925"
sys.path.insert(0, str(PREVIOUS))
import safe_inputs  # noqa: E402

END = pd.Timestamp("2026-01-01")
EXTRA_FEATURE_SOURCE = Path(r"D:\us-tech-quant-daily\A2_historical_top40\runs\20260924_gap_fill_complete\inference_features.parquet")
BASE_FEATURES = ["ret_1d", "ret_5d", "ret_20d", "realized_vol_20d", "downside_vol_20d",
                 "max_drawdown_20d", "volume_ratio_5d_20d", "price_vs_ma20", "distance_from_high_20d"]
FEATURES = ["raw_rank_strength", "raw_score_z", *BASE_FEATURES,
            *(f"lag_ret_{i:02d}" for i in range(10))]


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build() -> None:
    if (ROOT / "pre2026_panel.parquet").exists():
        raise RuntimeError("PREPARED_PANEL_ALREADY_EXISTS")
    mature_old, prices, _, lineage = safe_inputs.load_inputs()
    checkpoint = pq.read_table(safe_inputs.CHECKPOINT).to_pandas().rename(
        columns={"decision_date": "signal_date", "ticker_if_available": "ticker"})
    checkpoint["signal_date"] = pd.to_datetime(checkpoint.signal_date)
    assert checkpoint.signal_date.max() < END and checkpoint.groupby("signal_date").size().eq(40).all()
    grp = checkpoint.groupby("signal_date").raw_score
    checkpoint["raw_rank_strength"] = 1 - (checkpoint.raw_rank.astype(float) - 1) / 39
    checkpoint["raw_score_z"] = (checkpoint.raw_score - grp.transform("mean")) / grp.transform(lambda x: x.std(ddof=0))
    assert checkpoint.duplicated(["signal_date", "ticker"]).sum() == 0
    old = mature_old[["signal_date", "ticker", *BASE_FEATURES]]
    panel = checkpoint.merge(old, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    # The existing inference file mixes years. This independent preparation step
    # pushes a 2025-only date predicate into Arrow before pandas and exports no
    # 2026 values, statistics, coverage or report to the fit stage.
    extra = ds.dataset(EXTRA_FEATURE_SOURCE, format="parquet").to_table(
        columns=["trade_date", "ticker", *BASE_FEATURES],
        filter=(ds.field("trade_date") >= pd.Timestamp("2025-12-01").to_pydatetime()) &
               (ds.field("trade_date") < END.to_pydatetime()),
    ).to_pandas().rename(columns={"trade_date": "signal_date"})
    extra["signal_date"] = pd.to_datetime(extra.signal_date)
    overlap = panel.loc[panel.signal_date.ge("2025-12-01") & panel.ret_1d.notna()].merge(
        extra, on=["signal_date", "ticker"], suffixes=("_old", "_extra"))
    if overlap.empty:
        raise RuntimeError("EXTRA_FEATURE_OVERLAP_MISSING")
    max_error = max(float(np.nanmax(np.abs(overlap[f"{c}_old"] - overlap[f"{c}_extra"]))) for c in BASE_FEATURES)
    if max_error != 0:
        raise RuntimeError(f"EXTRA_FEATURE_COORDINATE_MISMATCH:{max_error}")
    add = panel.loc[panel.ret_1d.isna(), ["signal_date", "ticker"]].merge(
        extra, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    extra_lookup = add.set_index(["signal_date", "ticker"])
    for col in BASE_FEATURES:
        missing = panel[col].isna()
        if missing.any():
            keys = pd.MultiIndex.from_frame(panel.loc[missing, ["signal_date", "ticker"]])
            panel.loc[missing, col] = extra_lookup[col].reindex(keys).to_numpy()
    px = prices[["ticker", "trade_date", "open", "close"]].sort_values(["ticker", "trade_date"])
    one = px.groupby("ticker", sort=False).close.pct_change(fill_method=None)
    lag = px[["ticker", "trade_date"]].copy()
    for i in range(10):
        lag[f"lag_ret_{i:02d}"] = one.groupby(px.ticker, sort=False).shift(i)
    panel = panel.merge(lag.rename(columns={"trade_date": "signal_date"}),
                        on=["signal_date", "ticker"], how="left", validate="one_to_one")
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    dates = pd.DataFrame({"signal_date": calendar, "entry_date": pd.Series(calendar).shift(-1),
                          "label_end_date_5": pd.Series(calendar).shift(-6)})
    panel = panel.merge(dates, on="signal_date", how="left", validate="many_to_one")
    opens = px[["ticker", "trade_date", "open"]]
    panel = panel.merge(opens.rename(columns={"trade_date": "entry_date", "open": "entry_open"}),
                        on=["entry_date", "ticker"], how="left", validate="many_to_one")
    panel = panel.merge(opens.rename(columns={"trade_date": "label_end_date_5", "open": "end_open_5"}),
                        on=["label_end_date_5", "ticker"], how="left", validate="many_to_one")
    panel["y5"] = panel.end_open_5 / panel.entry_open - 1
    panel.loc[~np.isfinite(panel.y5), "y5"] = np.nan
    panel["y5_cost_positive"] = np.where(panel.y5.notna(), (panel.y5 > .001).astype(float), np.nan)
    panel["label_status"] = np.where(panel.label_end_date_5.isna(), "UNMATURED_AT_2025_END",
                                      np.where(panel.entry_open.isna() | panel.end_open_5.isna(), "MISSING_PRICE", "MATURE"))
    if panel.signal_date.max() >= END or panel.loc[panel.y5.notna(), "label_end_date_5"].max() >= END:
        raise RuntimeError("TRAINING_2026_LEAK")
    if panel.duplicated(["signal_date", "ticker"]).any() or panel.groupby("signal_date").size().ne(40).any():
        raise RuntimeError("PANEL_IDENTITY_OR_CARDINALITY")
    panel = panel.sort_values(["signal_date", "raw_rank", "ticker"])
    keep = ["signal_date", "ticker", "security_id", "raw_rank", "raw_score", "prediction_asof_date",
            "training_cutoff", "model_hash", "entry_date", "label_end_date_5", "entry_open", "end_open_5",
            "y5", "y5_cost_positive", "label_status", *FEATURES]
    panel[keep].to_parquet(ROOT / "pre2026_panel.parquet", index=False)
    counts = (panel.assign(year=panel.signal_date.dt.year).groupby(["year", "label_status"])
              .agg(rows=("ticker", "size"), dates=("signal_date", "nunique"), tickers=("ticker", "nunique"))
              .reset_index())
    counts.to_csv(ROOT / "pre2026_coverage.csv", index=False)
    manifest = {"status": "PRE2026_PHYSICAL_AND_ARROW_FILTERED", "cutoff_exclusive": str(END.date()),
                "rows": len(panel), "dates": panel.signal_date.nunique(), "tickers": panel.ticker.nunique(),
                "last_signal_date": str(panel.signal_date.max().date()),
                "last_mature_label_date": str(panel.loc[panel.y5.notna(), "label_end_date_5"].max().date()),
                "unmatured_rows": int(panel.label_status.eq("UNMATURED_AT_2025_END").sum()),
                "missing_price_rows": int(panel.label_status.eq("MISSING_PRICE").sum()),
                "base_features": BASE_FEATURES, "model_features": FEATURES,
                "extra_source": str(EXTRA_FEATURE_SOURCE), "extra_source_sha256": digest(EXTRA_FEATURE_SOURCE),
                "extra_overlap_rows": len(overlap), "extra_overlap_max_abs_error": max_error,
                "pre2026_source_lineage": lineage, "panel_sha256": digest(ROOT / "pre2026_panel.parquet"),
                "2026_economic_values_exposed_to_fit": False}
    (ROOT / "pre2026_manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"PREPARED rows={len(panel)} dates={manifest['dates']} late_feature_overlap={len(overlap)}")


if __name__ == "__main__":
    build()
