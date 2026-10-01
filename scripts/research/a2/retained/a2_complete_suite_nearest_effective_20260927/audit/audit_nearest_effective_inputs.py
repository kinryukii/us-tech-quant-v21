"""Independent, read-only acceptance audit for the nearest-effective 13F batch.

Only candidate identities, signal-time features, filing clocks, and pre-2026
label maturity are inspected. No 2026 outcomes, model scores, or P&L are read.
The report is written solely under this batch's audit directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
OLD = WORKSPACE / "a2_complete_suite_20260927"
STRICT = WORKSPACE / "a2_strict_method_retrain_20260926"
SOURCE = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1")
FULL_GATE = STRICT / "test2026_stage/r6_contract_correction/R6_FULL_CANDIDATE_INPUT_GATE.parquet"
Q2_BINDING = STRICT / "test2026_stage/fixed_window_binding/Q2_SOURCE_BINDING.json"
LAST_SIGNAL = pd.Timestamp("2026-09-22")
LAST_EXECUTION = pd.Timestamp("2026-09-23")
LAST_VALUATION = pd.Timestamp("2026-09-24")


def require(condition: bool, message: str) -> None:
    if not bool(condition):
        raise AssertionError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_columns(path: Path, columns: list[str]) -> pd.DataFrame:
    require(path.is_file(), f"missing required input: {path}")
    names = set(pq.ParquetFile(path).schema_arrow.names)
    require(set(columns) <= names, f"missing columns at {path}: {sorted(set(columns)-names)}")
    frame = pd.read_parquet(path, columns=columns)
    if "signal_date" in frame:
        frame["signal_date"] = pd.to_datetime(frame.signal_date).dt.normalize()
    return frame


def equal_keys(left: pd.DataFrame, right: pd.DataFrame, keys: list[str], label: str) -> None:
    require(not left.duplicated(keys).any(), f"duplicate {label} left keys")
    require(not right.duplicated(keys).any(), f"duplicate {label} right keys")
    a = left[keys].sort_values(keys, kind="mergesort").reset_index(drop=True)
    b = right[keys].sort_values(keys, kind="mergesort").reset_index(drop=True)
    require(a.equals(b), f"{label} keys differ: left={len(a)}, right={len(b)}")


def verify_old_frozen_batch() -> dict[str, object]:
    manifest = OLD / "evaluation_2026/cost_10/FROZEN_BEFORE_SCORING.json"
    frozen = json.loads(manifest.read_text(encoding="utf-8"))["source_hashes"]
    failed = [relative for relative, expected in frozen.items()
              if not (OLD / relative).is_file() or sha256(OLD / relative) != expected]
    require(not failed, f"historical batch changed after freeze: {failed[:10]}")
    return {"freeze_manifest_sha256": sha256(manifest),
            "frozen_files_checked": len(frozen), "frozen_files_changed": 0}


def check_finite_features(path: Path, features: list[str]) -> int:
    count = 0
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(columns=features, batch_size=8192):
        values = batch.to_pandas().to_numpy(dtype=np.float64, copy=False)
        require(np.isfinite(values).all(), f"nonfinite signal-time features in {path}")
        count += len(values)
    return count


def normalize_timing(timing: pd.DataFrame) -> pd.DataFrame:
    required = ["quarter", "quarter_effective_date", "latest_filing_date"]
    require(set(required) <= set(timing), "quarter timing is incomplete")
    q = timing[required].copy()
    for name in required[1:]:
        q[name] = pd.to_datetime(q[name]).dt.tz_localize(None)
    q = q.sort_values("quarter_effective_date", kind="mergesort").reset_index(drop=True)
    require(not q.isna().any().any(), "quarter timing contains nulls")
    require(not q.quarter.duplicated().any(), "quarter timing repeats a quarter")
    require(not q.quarter_effective_date.duplicated().any(), "quarter effective dates repeat")
    require(q.quarter_effective_date.gt(q.latest_filing_date).all(),
            "quarter effective date precedes its public filing")
    return q


def check_latest_effective(frame: pd.DataFrame, timing: pd.DataFrame,
                           quarter_column: str, label: str) -> dict[str, object]:
    q = normalize_timing(timing)
    dates = frame.signal_date.to_numpy(dtype="datetime64[ns]")
    positions = np.searchsorted(q.quarter_effective_date.to_numpy(dtype="datetime64[ns]"),
                                dates, side="right") - 1
    require((positions >= 0).all(), f"{label} contains a date before any effective 13F")
    expected = q.quarter.to_numpy(dtype=str)[positions]
    actual = frame[quarter_column].astype(str).to_numpy()
    require(np.array_equal(actual, expected), f"{label} is not the latest effective quarter")
    expected_effective = q.quarter_effective_date.to_numpy(dtype="datetime64[ns]")[positions]
    expected_filing = q.latest_filing_date.to_numpy(dtype="datetime64[ns]")[positions]
    require(np.array_equal(pd.to_datetime(frame.quarter_effective_date).to_numpy(dtype="datetime64[ns]"),
                           expected_effective), f"{label} row effective dates differ from manifest")
    require(np.array_equal(pd.to_datetime(frame.latest_filing_date).to_numpy(dtype="datetime64[ns]"),
                           expected_filing), f"{label} row filing dates differ from manifest")
    require((dates >= expected_effective).all() and (dates > expected_filing).all(),
            f"{label} uses unpublished or uneffective 13F")
    require(pd.api.types.is_bool_dtype(frame.new_buy_eligible), f"{label} buy flag is not boolean")
    require(frame.new_buy_eligible.notna().all() and frame.new_buy_eligible.all(),
            f"{label} contains an excluded latest-effective candidate")
    per_day = frame.groupby("signal_date")[quarter_column].nunique()
    require(per_day.eq(1).all(), f"{label} uses multiple active quarters on a signal day")
    previous_natural = (frame.signal_date.dt.to_period("Q") - 1).astype(str).to_numpy()
    carried = actual != previous_natural
    require(carried.any(), f"{label} never retains an older effective quarter")
    return {"rows": int(len(frame)), "signal_days": int(frame.signal_date.nunique()),
            "quarters": sorted(set(actual)), "carry_forward_rows": int(carried.sum()),
            "carry_forward_days": int(frame.signal_date[carried].nunique()),
            "first_signal": str(frame.signal_date.min().date()),
            "last_signal": str(frame.signal_date.max().date())}


def main() -> dict[str, object]:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--test-timing", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "audit/NEAREST_EFFECTIVE_INPUT_AUDIT.json")
    args = parser.parse_args()
    data = args.data_dir.resolve()
    timing_path = args.test_timing or data / "quarter_timing.csv"
    require(timing_path.is_file(), f"missing test quarter timing: {timing_path}")

    old_freeze = verify_old_frozen_batch()
    pre_columns = ["signal_date", "ticker", "cusip", "active_13f_quarter",
                   "latest_filing_date", "quarter_effective_date", "new_buy_eligible",
                   "execution_date", "label_end_date", "label_available",
                   "target_end_date", "target_context_available"]
    test_columns = ["signal_date", "ticker", "cusip", "title_of_class", "quarter",
                    "latest_filing_date", "quarter_effective_date", "new_buy_eligible",
                    "final_input_gate"]
    pre_context = read_columns(data / "pre2026_joint_context.parquet", pre_columns)
    pre_buy = read_columns(data / "pre2026_joint.parquet", pre_columns)
    test_context = read_columns(data / "test_features_context.parquet", test_columns)
    test_buy = read_columns(data / "test_features.parquet", test_columns)
    equal_keys(pre_context, pre_buy, ["signal_date", "ticker", "cusip", "active_13f_quarter"],
               "pre2026 context and buy pool")
    equal_keys(test_context, test_buy,
               ["signal_date", "ticker", "cusip", "title_of_class", "quarter"],
               "2026 verified context and buy pool")

    source_score = read_columns(SOURCE / "A/score_rank_ledger.parquet", ["signal_date", "ticker"])
    source_score = source_score.loc[source_score.signal_date.dt.year.isin([2023, 2024, 2025])]
    source_membership = read_columns(SOURCE / "universe/daily_eligible_universe_membership.parquet",
                                     ["signal_date", "ticker", "cusip", "active_13f_quarter"])
    source_membership = source_membership.loc[
        source_membership.signal_date.dt.year.isin([2023, 2024, 2025])]
    equal_keys(pre_context, source_score, ["signal_date", "ticker"], "pre2026 original score pool")
    equal_keys(pre_context, source_membership,
               ["signal_date", "ticker", "cusip", "active_13f_quarter"],
               "pre2026 original dynamic 13F membership")
    old_pre = read_columns(OLD / "data/pre2026_joint_context.parquet",
                           ["signal_date", "ticker", "cusip", "active_13f_quarter"])
    equal_keys(pre_context, old_pre, ["signal_date", "ticker", "cusip", "active_13f_quarter"],
               "pre2026 historical full context")

    full_gate = read_columns(FULL_GATE, ["signal_date", "ticker", "cusip", "title_of_class",
                                         "quarter", "final_input_gate"])
    require(len(full_gate) == 111868, "2026 full candidate window changed")
    verified = full_gate.final_input_gate.astype(str).str.startswith("INPUT_VERIFIED")
    unknown = full_gate.final_input_gate.astype(str).str.startswith("UNKNOWN")
    proven = full_gate.final_input_gate.astype(str).str.startswith("PROVEN")
    require((verified | unknown | proven).all(), "2026 gate has unclassified candidate rows")
    require(int(verified.sum() + unknown.sum() + proven.sum()) == len(full_gate),
            "2026 full candidate rows are not partitioned exactly once")
    equal_keys(test_context, full_gate.loc[verified],
               ["signal_date", "ticker", "cusip", "title_of_class", "quarter"],
               "2026 R6 verified subset")
    old_test = read_columns(OLD / "data/test_features_context.parquet",
                            ["signal_date", "ticker", "cusip", "title_of_class", "quarter"])
    equal_keys(test_context, old_test,
               ["signal_date", "ticker", "cusip", "title_of_class", "quarter"],
               "2026 historical verified context")
    require(test_context.final_input_gate.astype(str).str.startswith("INPUT_VERIFIED").all(),
            "2026 panel contains an unknown or proven-ineligible candidate")

    original_timing = read_columns(SOURCE / "universe/quarterly_universe_manifest.parquet",
                                   ["quarter", "latest_actual_filing_timestamp", "effective_date"])
    original_timing = original_timing.rename(columns={
        "latest_actual_filing_timestamp": "latest_filing_date",
        "effective_date": "quarter_effective_date"})
    pre_check = check_latest_effective(pre_context, original_timing,
                                       "active_13f_quarter", "pre2026 context")
    check_latest_effective(pre_buy, original_timing, "active_13f_quarter", "pre2026 buy")
    test_timing = pd.read_csv(timing_path)
    source_recent = normalize_timing(original_timing)
    joined = normalize_timing(test_timing).merge(source_recent, on="quarter", how="left",
                                                  suffixes=("", "_original"))
    historical = joined.quarter.ne("2026Q2")
    require(joined.loc[historical, "quarter_effective_date"].equals(
        joined.loc[historical, "quarter_effective_date_original"]),
        "test timing changed an original quarter effective date")
    require(joined.loc[historical, "latest_filing_date"].equals(
        joined.loc[historical, "latest_filing_date_original"]),
        "test timing changed an original quarter filing date")
    q2 = joined.loc[joined.quarter.eq("2026Q2")]
    require(len(q2) == 1, "test timing does not contain exactly one 2026Q2")
    q2_binding = json.loads(Q2_BINDING.read_text(encoding="utf-8"))
    require(q2.quarter_effective_date.iloc[0] == pd.Timestamp(q2_binding["initial_effective_date"]),
            "2026Q2 effective date differs from the saved source binding")
    test_check = check_latest_effective(test_context, test_timing, "quarter", "2026 context")
    check_latest_effective(test_buy, test_timing, "quarter", "2026 buy")

    require(pre_context.signal_date.dt.year.isin([2023, 2024, 2025]).all(),
            "pre2026 context includes a forbidden signal year")
    for frame, name in [(pre_context, "context"), (pre_buy, "buy")]:
        mature = frame.label_available.fillna(False).astype(bool)
        require(frame.loc[mature, "label_end_date"].lt(pd.Timestamp("2026-01-01")).all(),
                f"pre2026 {name} has a mature label ending in 2026")
        require(frame.loc[mature, "execution_date"].gt(frame.loc[mature, "signal_date"]).all(),
                f"pre2026 {name} has a nonfuture execution date")
        require(frame.loc[mature, "label_end_date"].gt(frame.loc[mature, "execution_date"]).all(),
                f"pre2026 {name} has an invalid label interval")
        target_valid = frame.target_context_available.fillna(False).astype(bool)
        require(frame.loc[target_valid, "target_end_date"].lt(pd.Timestamp("2026-01-01")).all(),
                f"pre2026 {name} has a target ending in 2026")
    require(test_context.signal_date.min() == pd.Timestamp("2026-01-02"),
            "2026 signal window start changed")
    require(test_context.signal_date.max() == LAST_SIGNAL,
            "2026 signal window end changed")
    calendar = read_columns(data / "calendar.parquet", ["trade_date", "is_test", "is_signal"])
    calendar.trade_date = pd.to_datetime(calendar.trade_date).dt.normalize()
    require(calendar.trade_date.max() == LAST_VALUATION and not calendar.trade_date.duplicated().any(),
            "2026 terminal valuation calendar changed")
    dates = pd.DatetimeIndex(calendar.trade_date).sort_values()
    end_position = dates.get_loc(LAST_SIGNAL)
    require(dates[end_position + 1] == LAST_EXECUTION and dates[end_position + 2] == LAST_VALUATION,
            "2026 last signal/next execution/terminal valuation clock changed")

    features = json.loads((OLD / "data/JOINT_DATA_AUDIT.json").read_text(encoding="utf-8"))["features"]
    require(len(features) == 32 and len(set(features)) == 32, "historical feature contract is not 32 columns")
    finite_rows = {filename: check_finite_features(data / filename, features) for filename in
                   ["pre2026_joint_context.parquet", "pre2026_joint.parquet",
                    "test_features_context.parquet", "test_features.parquet"]}
    require(finite_rows["pre2026_joint_context.parquet"] == len(pre_context),
            "pre2026 context feature scan row count differs")
    require(finite_rows["test_features_context.parquet"] == len(test_context),
            "2026 context feature scan row count differs")

    coverage = {"full_original_candidate_rows": int(len(full_gate)),
                "verified_subset_rows": int(verified.sum()),
                "unknown_rows": int(unknown.sum()), "proven_ineligible_rows": int(proven.sum()),
                "complete_signal_days": int(full_gate.assign(unknown=unknown).groupby(
                    "signal_date").unknown.sum().eq(0).sum()),
                "formal_full_pool_test_allowed": bool(not unknown.any())}
    require(coverage["unknown_rows"] > 0 and not coverage["formal_full_pool_test_allowed"],
            "2026 verified-subset boundary was silently upgraded")
    report = {"status": "PASS", "rule": "nearest publicly filed and effective 13F quarter at signal close",
              "pre2026": pre_check, "test2026_verified_subset": test_check,
              "test2026_full_pool_gate": coverage,
              "training_clock": {"development_years": [2023, 2024], "validation_year": 2025,
                                 "final_training_years": [2023, 2024, 2025],
                                 "mature_one_step_labels": int(pre_context.label_available.sum()),
                                 "maximum_mature_label_end": str(pre_context.loc[
                                     pre_context.label_available, "label_end_date"].max().date()),
                                 "2026_training_rows": 0},
              "test_clock": {"last_signal": str(LAST_SIGNAL.date()),
                             "last_execution": str(LAST_EXECUTION.date()),
                             "terminal_valuation": str(LAST_VALUATION.date())},
              "signal_time_feature_columns": len(features), "finite_feature_rows_checked": finite_rows,
              "historical_batch": old_freeze,
              "audit_fit_calls": 0, "audit_preprocessing_fit_calls": 0,
              "reads_2026_outcomes_or_economic_results": False,
              "input_sha256": {name: sha256(data / name) for name in
                               ["pre2026_joint_context.parquet", "pre2026_joint.parquet",
                                "test_features_context.parquet", "test_features.parquet"]}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    require(args.output.resolve().is_relative_to((ROOT / "audit").resolve()),
            "audit output must stay in the new batch audit directory")
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, ensure_ascii=False))
