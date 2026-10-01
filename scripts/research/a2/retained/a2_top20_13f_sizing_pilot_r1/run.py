"""Frozen pre-2026 Top100-observed sizing replay; no fitting or scoring."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from weights import allocate


OUT = Path(__file__).resolve().parent
MANIFEST = OUT / "RUN_MANIFEST.json"
ROOT = Path("D:/us-tech-quant-results")
SOURCE = ROOT / "A_VS_A2_QUARTERLY_13F_R1"
INTERVALS = ROOT / "A2_PIT13F_MATERIALIZATION_R1/effective_universe_intervals.parquet"
TIMING = ROOT / "A2_PIT13F_MATERIALIZATION_R1/quarterly_universe.parquet"
SURFACE_MANIFEST = ROOT / "A2_PRE2026_RAW_MOOMOO_REHAB_BUILDER_R2/surface_manifest.json"
R4 = Path("D:/us-tech-quant-worktrees/a2-raw-a2-true-return-attribution-r1-20260827-013537/scripts/v22/abcde_a2_r4_portfolio_translation_using_hgb_incumbent.py")
END = pd.Timestamp("2025-12-31")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def save_manifest(manifest: dict) -> None:
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def get_module(path: Path):
    spec = importlib.util.spec_from_file_location("frozen_r4_sizing", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_weights(signals: pd.DataFrame, intervals: pd.DataFrame, timing: pd.DataFrame):
    assert signals.signal_date.max() <= END and intervals.effective_end.max() <= END
    assert len(signals) == signals.signal_date.nunique() * 20
    assert signals.groupby("signal_date").ticker.nunique().eq(20).all()
    assert intervals.groupby("report_quarter").ticker.nunique().eq(intervals.groupby("report_quarter").size()).all()
    assert intervals.mapping_status.eq("RESOLVED").all()
    dates = timing.sort_values("effective_date")
    assert dates.effective_date.is_monotonic_increasing and dates.report_quarter.nunique() == len(dates)
    assert dates.report_date.is_monotonic_increasing
    assert (dates.report_date <= dates.latest_included_filing_timestamp).all()
    assert (dates.latest_included_filing_timestamp <= dates.effective_date).all()
    by_quarter = {q: part.set_index("ticker") for q, part in intervals.groupby("report_quarter")}
    rows, targets, statuses = [], {}, []
    for signal_date, day in signals.groupby("signal_date", sort=True):
        eligible = dates.loc[(dates.effective_date <= signal_date) & (dates.effective_end >= signal_date)]
        if len(eligible) != 1:
            raise RuntimeError(f"UNKNOWN_13F_CLOCK:{signal_date}")
        quarter = eligible.iloc[0].report_quarter
        source = by_quarter[quarter]
        names = day.sort_values("a2_rank").ticker.tolist()
        base = {name: 0.05 for name in names}
        amounts = {name: float(source.at[name, "aggregate_value_usd"]) for name in names if name in source.index}
        weights, status = allocate(base, amounts)
        targets[pd.Timestamp(signal_date)] = weights
        statuses.append((signal_date, status, quarter))
        for name in names:
            matched = name in source.index
            record = source.loc[name] if matched else None
            rows.append({"signal_date": signal_date, "ticker": name, "a2_rank": int(day.loc[day.ticker.eq(name), "a2_rank"].iloc[0]),
                         "report_quarter": quarter, "report_date": eligible.iloc[0].report_date,
                         "public_at_latest_included_filing_date": eligible.iloc[0].latest_included_filing_timestamp,
                         "effective_at": eligible.iloc[0].effective_date,
                         "source_filing": record.source_filing if matched else None,
                         "cusip": record.cusip if matched else None,
                         "institution_support_count": int(record.institution_support_count) if matched else 0,
                         "observed_amount_usd": amounts.get(name, 0.0),
                         "full_report_amount_status": "UNKNOWN_TOP100_TRUNCATED",
                         "input_status": "OBSERVED_TOP100" if matched else "NOT_LISTED_IN_OBSERVED_TOP100",
                         "B0_RAW": base[name], "B1_CAP": np.nan,
                         "B2_OBSERVED_TOP100": weights[name], "B3_13F_PORTFOLIO_SHARE": np.nan,
                         "B2_status": status})
    return pd.DataFrame(rows), targets, pd.DataFrame(statuses, columns=["signal_date", "B2_status", "report_quarter"])


def load_prices(codes: set[str]) -> pd.DataFrame:
    manifest = json.loads(SURFACE_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["max_date"] == "2025-12-31" and manifest["immutable"] is True
    assert codes <= set(manifest["materialized_transport_codes"]), sorted(codes - set(manifest["materialized_transport_codes"]))[:10]
    root = Path(manifest["surface_path"])
    parts = []
    for item in manifest["partitions"]:
        path = root / item["relative_path"]
        assert sha(path) == item["sha256"]
        if codes.intersection(item["codes"]):
            parts.append(pd.read_parquet(path, filters=[("moomoo_transport_code", "in", sorted(codes))],
                                         columns=["trade_date", "ticker", "open", "close", "autype", "moomoo_transport_code"]))
    prices = pd.concat(parts, ignore_index=True)
    assert prices.trade_date.max() <= END and prices.autype.astype(str).eq("PIT_FORWARD_REHAB_INDEX").all()
    qqq = []
    expected = {2023: "a5a35422629920b7f5d063acabbb04f0ad410ec9f7e504de7daadd3b9d249bf6",
                2024: "7e14eb6735e7660e6895ab1a9a4ee86fa3ed1bd3ea976c56aeecfd75411e5eb8",
                2025: "b8a8abb5a8bdd7cbf9cf44ebba2f54bc09b60612c6fd8a7b7951aa064f9abc89"}
    for year, digest in expected.items():
        path = Path(f"D:/us-tech-quant-data/moomoo/source/prices_qfq/year={year}/prices.parquet")
        assert sha(path) == digest
        part = pd.read_parquet(path, columns=["ticker", "trade_date", "open", "close", "autype"])
        qqq.append(part.loc[part.ticker.eq("QQQ")])
    prices = pd.concat([prices, *qqq], ignore_index=True)
    prices["trade_date"] = pd.to_datetime(prices.trade_date).dt.normalize()
    assert not prices.duplicated(["ticker", "trade_date"]).any()
    return prices


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["status"] == "SPEC_FROZEN_BEFORE_NEW_POLICY_OUTCOMES"
    assert sha(R4) == manifest["inputs"]["accounting"]["sha256"]
    signal_path = SOURCE / "A2/top20_selections.parquet"
    assert sha(signal_path) == manifest["inputs"]["raw_top20"]["sha256"]
    signals = pd.read_parquet(signal_path)
    intervals = pd.read_parquet(INTERVALS)
    timing = pd.read_parquet(TIMING)
    weights, targets, statuses = build_weights(signals, intervals, timing)
    for target in targets.values():
        values = np.fromiter(target.values(), dtype=float)
        assert np.isfinite(values).all() and (values >= 0).all() and abs(values.sum() - 1.0) <= 1e-12
    weights.to_csv(OUT / "WEIGHTS.csv", index=False)
    weights[["signal_date", "ticker", "report_quarter", "report_date", "public_at_latest_included_filing_date", "effective_at", "source_filing", "cusip",
             "institution_support_count", "observed_amount_usd", "full_report_amount_status", "input_status", "B2_status"]].to_csv(OUT / "INPUT_COVERAGE.csv", index=False)
    statuses.to_csv(OUT / "DAILY_COVERAGE.csv", index=False)
    manifest["window"].update({"actual_signal_start": str(signals.signal_date.min().date()),
                               "actual_signal_end": str(signals.signal_date.max().date()),
                               "signal_days": int(signals.signal_date.nunique()), "signal_rows": len(signals),
                               "actual_dates_pending_read": False})
    manifest["stages"]["thin_adapter"] = "COMPLETE"
    manifest["stages"]["targeted_tests"] = "3 PASSED; amendment and instrument semantics inherited from frozen upstream v17b, not independently re-tested here"
    manifest["stages"]["input_coverage"] = "COMPLETE"
    manifest["next_command"] = "python -B a2_top20_13f_sizing_pilot_r1/run.py"
    save_manifest(manifest)
    r4 = get_module(R4)
    prices = load_prices({"US." + x for x in signals.ticker.unique()})
    safe_signals = signals.copy()
    safe_signals["a1_rank"] = safe_signals["a2_rank"]  # R4 cardinality gate only; A2 ranks and members unchanged.
    original = r4.build_target_map
    try:
        baseline = original(safe_signals, "a2_rank", 20)
        r4.build_target_map = lambda *_args, **_kwargs: baseline
        b0 = r4.simulate_portfolio(safe_signals, prices, "B0_RAW", "a2_rank", 20, 10)
    finally:
        r4.build_target_map = original
    reference = pd.read_parquet(SOURCE / "A2/portfolio_daily.parquet")
    reference = reference.sort_values("execution_date")
    b0 = b0.sort_values("execution_date")
    assert len(b0) == len(reference) and b0.execution_date.reset_index(drop=True).equals(reference.execution_date.reset_index(drop=True))
    drift = float(np.max(np.abs(b0.net_return.to_numpy() - reference.reconstructed_daily_return.to_numpy())))
    manifest["baseline_reconciliation_max_abs_return_error"] = drift
    manifest["stages"]["baseline_reconciliation"] = "PASS" if drift <= 1e-12 else "FAIL"
    save_manifest(manifest)
    if drift > 1e-12:
        raise RuntimeError(f"B0_REFERENCE_DRIFT:{drift}")
    b0.to_parquet(OUT / "B0_DAILY.parquet", index=False)
    try:
        r4.build_target_map = lambda *_args, **_kwargs: targets
        b2 = r4.simulate_portfolio(safe_signals, prices, "B2_OBSERVED_TOP100", "a2_rank", 20, 10)
    finally:
        r4.build_target_map = original
    b2.to_parquet(OUT / "B2_DAILY.parquet", index=False)
    metrics = []
    for name, frame in [("B0_RAW", b0), ("B2_OBSERVED_TOP100", b2)]:
        for year, part in [("ALL", frame), *[(str(y), f) for y, f in frame.groupby("year")]]:
            m = r4.portfolio_metrics(part)
            metrics.append({"policy": name, "year": year, **m})
    pd.DataFrame(metrics).to_csv(OUT / "POLICY_METRICS.csv", index=False)
    manifest["stages"]["policy_replay"] = "B0_B2_COMPLETE_INDEX_COORDINATE_DIAGNOSTIC"
    manifest["prediction_fit_count"] = 0
    manifest["actual_execution_rows_each"] = len(b0)
    manifest["next_command"] = "Review WEIGHTS.csv, INPUT_COVERAGE.csv, B0_DAILY.parquet, B2_DAILY.parquet and POLICY_METRICS.csv"
    save_manifest(manifest)


if __name__ == "__main__":
    main()
