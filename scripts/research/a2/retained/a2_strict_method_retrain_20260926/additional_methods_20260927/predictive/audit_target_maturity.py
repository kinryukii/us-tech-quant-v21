"""Read-only rowwise audit of the original A2 pre-2026 target maturity."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
BASE = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1")
MATRIX = BASE / "A2/training_matrix.parquet"
REFERENCE = BASE / "A2/oof_predictions.parquet"
PRODUCER = Path(r"D:\us-tech-quant\scripts\v22\abcde_a2_r1_nonlinear_cross_sectional_modeling.py")
BUILDER = BASE / "scripts/run_rebuild.py"
QQQ_ROOT = Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq")
CUTOFF = pd.Timestamp("2026-01-01")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    frame = pd.read_parquet(MATRIX, columns=["signal_date", "ticker", "target", "target_end_date"])
    assert len(frame) == 520328 and not frame.duplicated(["signal_date", "ticker"]).any()
    assert frame.target.notna().all() and np.isfinite(frame.target.to_numpy(dtype=float)).all()
    assert frame.signal_date.notna().all() and frame.target_end_date.notna().all()
    assert frame.signal_date.lt(CUTOFF).all() and frame.target_end_date.lt(CUTOFF).all()
    assert frame.target_end_date.gt(frame.signal_date).all()
    # The original producer defines target_end_date as the 20-session endpoint.
    # Independently recalculate this mapping from the source QQQ calendar.
    pieces = []
    calendar_sources = {}
    for year in range(2020, 2027):
        path = QQQ_ROOT / f"year={year}/prices.parquet"
        if not path.exists():
            continue
        part = pd.read_parquet(path, columns=["ticker", "trade_date"])
        pieces.append(part.loc[part.ticker.astype(str).str.upper().eq("QQQ"), "trade_date"])
        calendar_sources[str(path)] = sha(path)
    calendar = pd.DatetimeIndex(pd.concat(pieces, ignore_index=True).drop_duplicates().sort_values())
    position = pd.Series(np.arange(len(calendar), dtype=np.int32), index=calendar)
    positions = frame.signal_date.map(position)
    assert positions.notna().all()
    expected = calendar.take(positions.to_numpy(dtype=np.int32) + 20)
    matching = pd.DatetimeIndex(frame.target_end_date).equals(pd.DatetimeIndex(expected))
    assert matching, "Some saved target maturity differs from the original 20-session calendar mapping"
    column_checks = {}
    for name in ["signal_date", "ticker", "target", "target_end_date"]:
        values = pd.util.hash_pandas_object(frame[name], index=False).to_numpy(dtype=np.uint64)
        column_checks[name] = {
            "pandas_hash64_le_sha256": hashlib.sha256(values.astype("<u8", copy=False).tobytes()).hexdigest(),
            "null_count": int(frame[name].isna().sum()),
            "unique_count": int(frame[name].nunique()),
        }
    reference = pd.read_parquet(REFERENCE, columns=["signal_date", "ticker"])
    fold_checks = {}
    expected_counts = {2023: 208523, 2024: 305359, 2025: 409674}
    for year in (2023, 2024, 2025):
        first_evaluation_date = reference.loc[reference.signal_date.dt.year.eq(year), "signal_date"].min()
        fold = frame.loc[frame.signal_date.lt(pd.Timestamp(f"{year}-01-01"))
                         & frame.target_end_date.lt(first_evaluation_date)]
        assert len(fold) == expected_counts[year]
        assert fold.target_end_date.lt(first_evaluation_date).all()
        fold_checks[str(year)] = {
            "first_evaluation_date": str(first_evaluation_date.date()),
            "train_rows": len(fold), "train_signal_max": str(fold.signal_date.max().date()),
            "train_target_end_max": str(fold.target_end_date.max().date()),
            "rows_crossing_evaluation_start": 0,
            "rows_target_maturity_2026_plus": int(fold.target_end_date.ge(CUTOFF).sum()),
        }
    daily = frame.groupby("signal_date", sort=True).agg(
        training_rows=("ticker", "size"), securities=("ticker", "nunique"),
        max_label_maturity=("target_end_date", "max"),
        min_label_maturity=("target_end_date", "min"),
    ).reset_index()
    daily["all_label_maturities_pre2026"] = daily.max_label_maturity.lt(CUTOFF)
    daily["max_horizon_sessions"] = 20
    assert daily.all_label_maturities_pre2026.all()
    output = HERE / "TARGET_MATURITY_BY_SIGNAL_DATE.csv"
    daily.to_csv(output, index=False)
    report = {
        "status": "PASS_ALL_SAVED_TRAINING_LABELS_MATURED_PRE2026",
        "training_matrix_sha256": sha(MATRIX),
        "row_count_checked": len(frame), "signal_date_count_checked": int(len(daily)),
        "unique_tickers_checked": int(frame.ticker.nunique()),
        "first_signal_date": str(frame.signal_date.min().date()),
        "last_signal_date": str(frame.signal_date.max().date()),
        "max_saved_20_session_label_maturity": str(frame.target_end_date.max().date()),
        "rows_signal_2026_plus": int(frame.signal_date.ge(CUTOFF).sum()),
        "rows_label_maturity_2026_plus": int(frame.target_end_date.ge(CUTOFF).sum()),
        "rows_target_missing_or_nonfinite": int((~np.isfinite(frame.target.to_numpy(dtype=float))).sum()),
        "rows_20_session_mapping_mismatch": 0,
        "column_checks": column_checks,
        "fold_checks": fold_checks,
        "source_producer_sha256": sha(PRODUCER),
        "source_builder_sha256": sha(BUILDER),
        "source_builder_guards": [
            "builder raw stock dates < 2026-01-01 before adjusted_price_frame",
            "builder QQQ calendar < 2026-01-01 before feature and target construction",
            "builder final train matrix requires target_end_date < 2026-01-01",
            "producer target_end_date = target_end_date_20d; all 3/5/10/20 horizons finite for a nonmissing target",
        ],
        "current_qqq_calendar_source_sha256": calendar_sources,
        "daily_proof_path": str(output), "daily_proof_sha256": sha(output),
        "training_methods_in_this_directory": ["logistic_positive_target", "distribution_quantile_function"],
        "training_methods_read_y_from_original_matrix_only": True,
    }
    (HERE / "TARGET_MATURITY_AUDIT.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ["status", "row_count_checked", "signal_date_count_checked",
                                               "max_saved_20_session_label_maturity",
                                               "rows_label_maturity_2026_plus", "rows_20_session_mapping_mismatch"]}, indent=2))


if __name__ == "__main__":
    main()
