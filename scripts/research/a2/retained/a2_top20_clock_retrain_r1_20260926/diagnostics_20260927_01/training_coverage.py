"""Read-only, pre-2026 time-coverage diagnostic for the sealed R1 training run."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


CUTOFF = pd.Timestamp("2026-01-01")
FOLDS = (("2024", "2024-01-01", "2025-01-01"),
         ("2025", "2025-01-01", "2026-01-01"),
         ("FINAL", "2026-01-01", None))
PANEL_COLUMNS = ["signal_date", "ticker", "security_id", "prediction_asof_date",
                 "training_cutoff", "model_hash", "label_end_date_5", "y5", "label_status"]


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def date(value: object) -> str | None:
    if pd.isna(value):
        return None
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def bounded_parquet(path: Path, field: str) -> pq.ParquetFile:
    source = pq.ParquetFile(path)
    index = source.schema_arrow.names.index(field)
    for group in range(source.metadata.num_row_groups):
        stats = source.metadata.row_group(group).column(index).statistics
        if stats is None or not stats.has_min_max or pd.Timestamp(stats.max) >= CUTOFF:
            raise RuntimeError(f"UNPROVEN_PRE2026_ROW_GROUP:{path.name}:{group}:{field}")
    return source


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, default=Path("/bundle"))
    parser.add_argument("--out", type=Path, default=Path("/out"))
    args = parser.parse_args()
    panel_path = args.bundle / "data" / "panel.parquet"
    prices_path = args.bundle / "data" / "prices.parquet"
    trials_path = args.bundle / "supervised_trials.csv"
    run_path = args.bundle / "training_run.json"
    manifest = json.loads((args.bundle / "input_manifest.json").read_text(encoding="utf-8"))
    if manifest["cutoff_exclusive"] != "2026-01-01":
        raise RuntimeError("CUTOFF_IDENTITY_MISMATCH")
    for path, key in ((panel_path, "panel_sha256"), (prices_path, "prices_sha256")):
        if sha256(path) != manifest[key]:
            raise RuntimeError(f"SEALED_INPUT_HASH_MISMATCH:{path.name}")
    panel_source = bounded_parquet(panel_path, "signal_date")
    bounded_parquet(panel_path, "label_end_date_5")
    bounded_parquet(prices_path, "trade_date")
    if not set(PANEL_COLUMNS).issubset(panel_source.schema_arrow.names):
        raise RuntimeError("PANEL_FIELDS_MISSING")
    panel = panel_source.read(columns=PANEL_COLUMNS).to_pandas()
    for field in ("signal_date", "prediction_asof_date", "training_cutoff", "label_end_date_5"):
        panel[field] = pd.to_datetime(panel[field])
    if panel.empty or panel.signal_date.ge(CUTOFF).any():
        raise RuntimeError("PANEL_DATE_BOUNDARY")
    if panel.duplicated(["signal_date", "ticker"]).any() or panel.groupby("signal_date").size().ne(40).any():
        raise RuntimeError("TOP40_DAILY_KEY_OR_DEPTH")
    if panel.prediction_asof_date.gt(panel.signal_date).any():
        raise RuntimeError("A2_PREDICTION_ASOF_FUTURE")
    if panel.training_cutoff.ge(panel.signal_date).any():
        raise RuntimeError("A2_TRAINING_CUTOFF_FUTURE")
    mature = (panel.label_end_date_5.notna() & panel.label_end_date_5.lt(CUTOFF)
              & np.isfinite(panel.y5.to_numpy(float)) & panel.label_status.eq("MATURE"))
    if mature.sum() != 49960:
        raise RuntimeError(f"MATURE_LABEL_COUNT_CHANGED:{int(mature.sum())}")
    panel["year"] = panel.signal_date.dt.year

    # QQQ is the sealed synthetic XNYS session marker, not a benchmark return.
    price_dates = pq.read_table(prices_path, columns=["ticker", "trade_date"]).to_pandas()
    sessions = pd.DatetimeIndex(pd.to_datetime(price_dates.loc[price_dates.ticker.eq("QQQ"), "trade_date"]).unique()).sort_values()
    if len(sessions) == 0 or sessions.max() >= CUTOFF:
        raise RuntimeError("CALENDAR_MARKER_BOUNDARY")
    years = []
    for year, frame in panel.groupby("year", sort=True):
        signal_dates = pd.DatetimeIndex(frame.signal_date.unique()).sort_values()
        year_sessions = sessions[sessions.year == year]
        if not signal_dates.isin(year_sessions).all():
            raise RuntimeError(f"SIGNAL_NOT_IN_XNYS_CALENDAR:{year}")
        missing = year_sessions.difference(signal_dates)
        years.append({
            "year": int(year), "rows": int(len(frame)), "signal_days": int(len(signal_dates)),
            "first_signal": date(signal_dates.min()), "last_signal": date(signal_dates.max()),
            "unique_security_ids": int(frame.security_id.nunique()),
            "mature_label_rows": int(mature[frame.index].sum()),
            "unmatured_label_rows": int((~mature[frame.index]).sum()),
            "calendar_sessions": int(len(year_sessions)),
            "calendar_days_without_signal": [date(x) for x in missing],
            "a2_model_hash_count": int(frame.model_hash.nunique()),
            "a2_training_cutoffs": sorted({date(x) for x in frame.training_cutoff.unique()}),
            "a2_prediction_asof_after_signal_rows": int(frame.prediction_asof_date.gt(frame.signal_date).sum()),
        })

    training_run = json.loads(run_path.read_text(encoding="utf-8"))
    trials = pd.read_csv(trials_path)
    folds = []
    for name, start_str, stop_str in FOLDS:
        start = pd.Timestamp(start_str)
        stop = pd.Timestamp(stop_str) if stop_str else None
        before_start = panel.signal_date.lt(start)
        train = panel.loc[before_start & panel.label_end_date_5.lt(start) & mature]
        excluded = panel.loc[before_start & ~(panel.label_end_date_5.lt(start) & mature)]
        valid = panel.loc[panel.signal_date.ge(start) & panel.signal_date.lt(stop)] if stop is not None else panel.iloc[0:0]
        recorded = training_run["fold_eligibility"][name]
        trial = trials.loc[trials.fold.eq(name)]
        if len(train) != recorded["train_rows"] or len(trial) != 9 or not trial.train_rows.eq(len(train)).all():
            raise RuntimeError(f"FOLD_RECORDED_COUNT_MISMATCH:{name}")
        if date(train.signal_date.max()) != recorded["last_signal"] or date(train.label_end_date_5.max()) != recorded["last_mature_label"]:
            raise RuntimeError(f"FOLD_RECORDED_DATE_MISMATCH:{name}")
        if not trial.valid_rows.eq(len(valid)).all():
            raise RuntimeError(f"FOLD_VALID_COUNT_MISMATCH:{name}")
        folds.append({
            "fold": name, "start_exclusive_training": date(start),
            "validation_stop_exclusive": date(stop) if stop is not None else None,
            "train_rows": int(len(train)), "train_signal_days": int(train.signal_date.nunique()),
            "train_first_signal": date(train.signal_date.min()),
            "train_last_signal": date(train.signal_date.max()),
            "train_last_label_end": date(train.label_end_date_5.max()),
            "pre_start_rows_excluded_for_label_maturity": int(len(excluded)),
            "validation_rows": int(len(valid)), "validation_signal_days": int(valid.signal_date.nunique()),
            "validation_first_signal": date(valid.signal_date.min()),
            "validation_last_signal": date(valid.signal_date.max()),
            "validation_labels_mature_by_fold_end": int((valid.label_end_date_5.lt(stop) & mature[valid.index]).sum()) if stop is not None else 0,
        })

    output = {
        "status": "PRE2026_COVERAGE_DIAGNOSTIC_ONLY", "market_fits_added": 0,
        "rl_updates_added": 0, "test_inference_added": 0,
        "source_panel_sha256": manifest["panel_sha256"],
        "source_prices_sha256": manifest["prices_sha256"],
        "source_training_run_sha256": sha256(run_path),
        "source_supervised_trials_sha256": sha256(trials_path),
        "panel_rows": int(len(panel)), "signal_days": int(panel.signal_date.nunique()),
        "signal_min": date(panel.signal_date.min()), "signal_max": date(panel.signal_date.max()),
        "mature_label_rows": int(mature.sum()), "unmatured_label_rows": int((~mature).sum()),
        "yearly": years, "folds": folds,
        "13f_effective_date_field_in_consumed_panel": False,
        "13f_daily_effective_quarter_verified_by_this_run": False,
        "13f_gap_reason": "Consumed R1 panel lacks filing, active-quarter and effective-date fields; no mixed-year upstream 13F ledger was mounted.",
        "scope": "Sealed pre-2026 panel and calendar only; no model fit or 2026 source read.",
    }
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "training_coverage.json"
    if path.exists():
        raise RuntimeError("OUTPUT_EXISTS_NON_OVERWRITE")
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"TRAINING_COVERAGE_PASS rows={len(panel)} days={panel.signal_date.nunique()} mature={int(mature.sum())}")


if __name__ == "__main__":
    main()
