"""Freeze the shared pre-2026 TOP20 panel; this module never opens 2026 data."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
R1 = WORKSPACE / "a2_13f_learned_sizing_pre2026_test2026_r1"
sys.path.insert(0, str(R1))
from train_pre2026 import load_data  # noqa: E402

FEATURES = ["r", "log_sigma20", "u", "u_squared", "v", "v_squared",
            "breadth", "r_times_v", "age_times_v"]
FOLDS = {
    "D1": {"train_cutoff": "2023-12-31", "validation_start": "2024-01-01", "validation_end": "2024-06-30"},
    "D2": {"train_cutoff": "2024-06-30", "validation_start": "2024-07-01", "validation_end": "2024-12-31"},
    "V25": {"train_cutoff": "2024-12-31", "validation_start": "2025-01-01", "validation_end": "2025-12-31"},
    "FINAL": {"train_cutoff": "2025-12-31"},
}


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def market_time(dates: pd.DatetimeIndex, hour: int, minute: int = 0) -> pd.DatetimeIndex:
    return (dates.tz_localize("America/New_York") + pd.Timedelta(hours=hour, minutes=minute)).tz_convert("UTC")


def main() -> None:
    target = HERE / "PRE2026_SHARED_PANEL.parquet"
    if target.exists():
        raise RuntimeError("FROZEN_PANEL_ALREADY_EXISTS")
    panel, dates, execution, path_end, usable, raw, name_ids, opens, calendar, prices = load_data()
    assert dates.max() < pd.Timestamp("2026-01-01")
    assert len(panel) == 15000 and len(dates) == 750 and raw.shape == (750, 20, 9)
    assert set(panel.mapping_status) == {"RESOLVED"}
    assert panel.groupby("signal_date").size().eq(20).all()
    assert not panel.duplicated(["signal_date", "cusip"]).any()
    entry = np.take_along_axis(opens[calendar.get_indexer(execution)], name_ids, axis=1)
    end = np.take_along_axis(opens[calendar.get_indexer(path_end)], name_ids, axis=1)
    assert np.isfinite(entry).all() and np.isfinite(end).all()
    assert (entry > 0).all() and (end > 0).all()
    y = end / entry - 1.0
    result = panel[["signal_date", "ticker", "cusip", "a2_rank", "a2_prediction",
                    "report_quarter", "report_date", "latest_included_filing_timestamp",
                    "input_status", "fallback_reason", "full_vh_usable"]].copy()
    result = result.rename(columns={"cusip": "experiment_security_key",
                                    "a2_rank": "raw_a2_rank"})
    for i, name in enumerate(FEATURES):
        result[name] = raw[:, :, i].reshape(-1)
    result["base_usable_day"] = np.repeat(usable, 20)
    result["execution_date"] = np.repeat(execution.to_numpy(), 20)
    result["label_end_date"] = np.repeat(path_end.to_numpy(), 20)
    result["signal_available_at_utc"] = np.repeat(market_time(dates, 16).to_numpy(), 20)
    result["execution_at_utc"] = np.repeat(market_time(execution, 9, 30).to_numpy(), 20)
    result["label_available_at_utc"] = np.repeat(market_time(path_end, 9, 30).to_numpy(), 20)
    result["entry_open"] = entry.reshape(-1)
    result["end_open"] = end.reshape(-1)
    result["gross_return_decimal"] = y.reshape(-1)
    result["up_label"] = (result.gross_return_decimal > 0).astype("int8")
    assert np.isfinite(result.loc[result.base_usable_day, FEATURES].to_numpy(float)).all()
    assert result.signal_available_at_utc.max() < pd.Timestamp("2026-01-01", tz="UTC")
    assert result.label_available_at_utc.max() < pd.Timestamp("2026-01-01", tz="UTC")
    source_filing = pd.to_datetime(result.latest_included_filing_timestamp, utc=True, errors="coerce")
    if (source_filing.notna() & source_filing.gt(result.signal_available_at_utc)).any():
        raise RuntimeError("FUTURE_13F_SOURCE_IN_SHARED_PANEL")
    result.to_parquet(target, index=False)
    # This is a read-only reconstruction of the existing frozen price surface.
    # The pre-2023 tail is needed only for the four train-only risk snapshots.
    px = prices.loc[prices.trade_date.ge("2022-01-01") & prices.trade_date.lt("2026-01-01"),
                    ["ticker", "trade_date", "open", "close"]].copy()
    assert not px.duplicated(["ticker", "trade_date"]).any()
    px.to_parquet(HERE / "PRE2026_PRICE_COORDINATE.parquet", index=False)
    coverage = (result.assign(year=result.signal_date.dt.year)
                .groupby("year").agg(signal_days=("signal_date", "nunique"),
                                     rows=("ticker", "size"),
                                     base_usable_rows=("base_usable_day", "sum"))
                .reset_index())
    coverage.to_csv(HERE / "PRE2026_INPUT_COVERAGE.csv", index=False)
    partitions = {}
    for name, fold in FOLDS.items():
        cutoff = pd.Timestamp(fold["train_cutoff"], tz="UTC") + pd.Timedelta(days=1)
        train = result.base_usable_day & result.label_available_at_utc.lt(cutoff)
        item = {"train_rows": int(train.sum()),
                "train_days": int(result.loc[train, "signal_date"].nunique()),
                "train_last_label_end": str(result.loc[train, "label_end_date"].max().date())}
        if "validation_start" in fold:
            val = (result.base_usable_day &
                   result.signal_date.between(fold["validation_start"], fold["validation_end"]) &
                   result.label_end_date.le(pd.Timestamp(fold["validation_end"])))
            item.update(validation_rows=int(val.sum()),
                        validation_days=int(result.loc[val, "signal_date"].nunique()))
        partitions[name] = item
    manifest = {
        "task": "TOP20_MULTIMETHOD_PRE2026_TEST2026_R1",
        "test_asof": "2026-09-23T18:40:43Z",
        "status": "PRE2026_SHARED_PANEL_FROZEN_NO_MODEL_FIT",
        "rows": len(result), "signal_days": len(dates), "base_usable_days": int(usable.sum()),
        "features": FEATURES,
        "optional_feature_group": "NOT_INCLUDED_BECAUSE_ORIGINAL_FROZEN_PRICE_SURFACE_HAS_NO_HIGH_LOW_VOLUME",
        "feature_contract": "Original R1 nine columns in original order; 20 completed same-coordinate closes for volatility; no optional feature selection by outcome.",
        "security_key_contract": "Experiment-local original 13F CUSIP; not the prospective September 2026 permanent UID allocation. No CUSIP has multiple tickers in this panel; same-ticker CUSIP changes remain distinct securities.",
        "label_contract": "Next legal execution open to following rebalance open, gross same-coordinate decimal return; up_label is return>0. Original price surface only gives day fields, so 09:30 ET denotes contract-level open availability, not observed tick timestamp.",
        "train_partition_contract": "Rows require base_usable_day and label_available_at strictly before the next UTC day after the fold cutoff; validation requires path_end by validation end.",
        "folds": FOLDS, "partition_counts": partitions,
        "source_paths": {"old_r1_panel": str(R1 / "PIT_PRE2026_TOP20_VH_PANEL.parquet"),
                         "old_r1_price_surface": r"D:\us-tech-quant-results\A2_PRE2026_RAW_MOOMOO_REHAB_BUILDER_R2\surface_manifest.json"},
        "source_hashes": {"old_r1_panel": sha(R1 / "PIT_PRE2026_TOP20_VH_PANEL.parquet"),
                          "old_r1_price_surface": sha(Path(r"D:\us-tech-quant-results\A2_PRE2026_RAW_MOOMOO_REHAB_BUILDER_R2\surface_manifest.json"))},
        "artifacts": {"PRE2026_SHARED_PANEL.parquet": sha(target),
                      "PRE2026_PRICE_COORDINATE.parquet": sha(HERE / "PRE2026_PRICE_COORDINATE.parquet"),
                      "PRE2026_INPUT_COVERAGE.csv": sha(HERE / "PRE2026_INPUT_COVERAGE.csv")},
        "old_r1_modified": False, "new_fit_calls": 0,
    }
    (HERE / "PRE2026_INPUT_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(result), "usable_days": int(usable.sum()), "partitions": partitions}))


if __name__ == "__main__":
    main()
