"""Build physically isolated, source-bound PTO inputs without reading test prices.

This script never fits or loads a model and never reads an account result. The
2026 price file is copied as bytes and inspected only through Parquet metadata.
Numerical test-price loading belongs to the frozen evaluation runner.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent
WS = ROOT.parent
DATA = ROOT / "data"
AUDITS = ROOT / "audits"
LATEST = WS / "a2_latest_effective_joint_20260927/data"
QUALIFIED = WS / "a2_qualification_holdings_v1_20260927/data"
STRICT = WS / "a2_strict_method_retrain_20260926"
ORIGINAL = Path("D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1")
INVENTORY = WS / "a2_ensemble_attribution_20260928_r1/qualification_all_candidates.parquet"
FEATURES = [
    "ret_1d", "ret_3d", "ret_5d", "ret_10d", "ret_20d", "ret_40d", "ret_60d", "ret_120d",
    "price_vs_ma10", "price_vs_ma20", "price_vs_ma50", "price_vs_ma120", "ma10_vs_ma20",
    "ma20_vs_ma50", "ma50_vs_ma120", "realized_vol_5d", "realized_vol_10d", "realized_vol_20d",
    "realized_vol_60d", "downside_vol_20d", "upside_vol_20d", "distance_from_high_20d",
    "distance_from_high_60d", "distance_from_low_20d", "distance_from_low_60d",
    "max_drawdown_20d", "max_drawdown_60d", "avg_volume_20d", "avg_volume_60d",
    "volume_ratio_5d_20d", "volume_ratio_20d_60d", "avg_dollar_volume_20d",
]
KEY = ["signal_date", "ticker"]
BOUNDARY = pd.Timestamp("2026-01-01")


def sha(path: Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str,
                               allow_nan=False), encoding="utf-8")


def copy_exact(source: Path, destination: Path, sources: dict[str, str]) -> None:
    if source.resolve() == destination.resolve():
        raise ValueError("SOURCE_MUST_NOT_BE_OVERWRITTEN")
    before = sha(source)
    sources[str(source.resolve())] = before
    shutil.copyfile(source, destination)
    if sha(destination) != before or sha(source) != before:
        raise ValueError("COPY_OR_SOURCE_HASH_CHANGED")


def check_latest_effective(frame: pd.DataFrame, timing: pd.DataFrame,
                           quarter_column: str) -> dict[str, int]:
    q = timing.sort_values("quarter_effective_date").reset_index(drop=True)
    if q.quarter.duplicated().any() or q.quarter_effective_date.duplicated().any():
        raise ValueError("DUPLICATE_QUARTER_CLOCK")
    if not q.latest_filing_date.lt(q.quarter_effective_date).all():
        raise ValueError("INVALID_QUARTER_FILING_CLOCK")
    dates = pd.to_datetime(frame.signal_date)
    positions = np.searchsorted(q.quarter_effective_date.to_numpy(),
                                dates.to_numpy(), side="right") - 1
    if (positions < 0).any():
        raise ValueError("SIGNAL_PRECEDES_KNOWN_QUARTER")
    expected = q.quarter.to_numpy()[positions]
    actual = frame[quarter_column].astype(str).to_numpy()
    mismatch = actual != expected
    filing_future = dates.to_numpy() <= q.latest_filing_date.to_numpy()[positions]
    early = dates.to_numpy() < q.quarter_effective_date.to_numpy()[positions]
    if mismatch.any() or filing_future.any() or early.any():
        raise ValueError("NOT_LATEST_PUBLIC_EFFECTIVE_13F_QUARTER")
    for column in ["latest_filing_date", "quarter_effective_date"]:
        if column in frame:
            if not np.array_equal(pd.to_datetime(frame[column]).to_numpy(),
                                  q[column].to_numpy()[positions]):
                raise ValueError(f"PANEL_CLOCK_DIFFERS:{column}")
    return {"rows": int(len(frame)), "quarter_mismatches": int(mismatch.sum()),
            "filing_not_before_signal": int(filing_future.sum()),
            "premature_effective": int(early.sum())}


def check_next_open_labels(panel: pd.DataFrame, prices: pd.DataFrame) -> dict[str, object]:
    if not prices.trade_date.lt(BOUNDARY).all():
        raise ValueError("PHYSICAL_PRE2026_PRICES_CONTAIN_TEST_YEAR")
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    positions = np.searchsorted(calendar.to_numpy(), panel.signal_date.to_numpy())
    if not np.array_equal(calendar.to_numpy()[positions], panel.signal_date.to_numpy()):
        raise ValueError("SIGNAL_OUTSIDE_TRADING_CALENDAR")
    for field, offset in [("execution_date", 1), ("label_end_date", 2)]:
        expected = np.full(len(panel), np.datetime64("NaT"), dtype="datetime64[ns]")
        valid = positions + offset < len(calendar)
        expected[valid] = calendar.to_numpy()[positions[valid] + offset]
        actual = panel[field].to_numpy()
        equal = (actual == expected) | (np.isnat(actual) & np.isnat(expected))
        if not equal.all():
            raise ValueError(f"NEXT_OPEN_CLOCK_MISMATCH:{field}")
    known = panel.loc[panel.label_available].copy()
    opening = prices.set_index(["ticker", "trade_date"]).open
    first = opening.reindex(pd.MultiIndex.from_arrays([known.ticker, known.execution_date])).to_numpy()
    last = opening.reindex(pd.MultiIndex.from_arrays([known.ticker, known.label_end_date])).to_numpy()
    rebuilt = last / first - 1.0
    error = np.abs(rebuilt - known.y_next_open.to_numpy())
    if not np.isfinite(rebuilt).all() or not (error <= 1e-12).all():
        raise ValueError("LABEL_NOT_RECONSTRUCTED_FROM_BOUND_PRICE")
    return {"available_labels": int(len(known)), "unavailable_labels_retained": int((~panel.label_available).sum()),
            "maximum_absolute_reconstruction_error": float(error.max()),
            "execution_clock_mismatches": 0, "label_end_clock_mismatches": 0,
            "scope": "internal frozen affine index-coordinate reconstruction only"}


def verify_existing() -> None:
    bindings = json.loads((ROOT / "input_paths.json").read_text(encoding="utf-8"))
    for path, expected in bindings["source_sha256"].items():
        if sha(Path(path)) != expected:
            raise ValueError(f"SOURCE_CHANGED:{path}")
    for path, expected in bindings["output_sha256"].items():
        if sha(Path(path)) != expected:
            raise ValueError(f"ISOLATED_INPUT_CHANGED:{path}")
    print(json.dumps({"status": "PASS_EXISTING_BINDINGS", "sources": len(bindings["source_sha256"]),
                      "outputs": len(bindings["output_sha256"])}), flush=True)


def build() -> None:
    if ROOT.name != "a2_pto_full_compat_20260928_r2":
        raise ValueError("BUILDER_RESTRICTED_TO_NEW_BATCH")
    if (ROOT / "input_paths.json").exists():
        raise FileExistsError("INPUT_BATCH_ALREADY_BUILT; use --verify")
    if (ROOT / "FROZEN_BEFORE_2026.json").exists() or (ROOT / "BATCH_FREEZE.json").exists():
        raise RuntimeError("FROZEN_BATCH_INPUTS_MUST_NOT_BE_REBUILT")
    DATA.mkdir(parents=True, exist_ok=True)
    AUDITS.mkdir(parents=True, exist_ok=True)
    sources: dict[str, str] = {}

    pre_source = LATEST / "pre2026_joint_context.parquet"
    sources[str(pre_source.resolve())] = sha(pre_source)
    pre = pd.read_parquet(pre_source)
    if len(pre) != 313668 or pre.duplicated(KEY).any() or not pre.new_buy_eligible.all():
        raise ValueError("PRE2026_AVAILABLE_FULL_CANDIDATE_CONTRACT_MISMATCH")
    if not pre.signal_date.lt(BOUNDARY).all() or not np.isfinite(pre[FEATURES].to_numpy(float)).all():
        raise ValueError("NON_PRE2026_OR_NONFINITE_TRAINING_INPUT")
    if not pre.loc[pre.label_available, "label_end_date"].lt(BOUNDARY).all():
        raise ValueError("NON_PRE2026_AVAILABLE_LABEL")
    pre["y_abs_next_open"] = np.where(pre.label_available, np.abs(pre.y_next_open), np.nan)
    pre.to_parquet(DATA / "pre_panel.parquet", index=False)
    copy_exact(STRICT / "results/pre2026_original_price_coordinate.parquet", DATA / "pre_prices.parquet", sources)
    prices = pd.read_parquet(DATA / "pre_prices.parquet")
    label_audit = check_next_open_labels(pre, prices)

    copy_exact(LATEST / "quarter_timing.csv", DATA / "quarter_timing.csv", sources)
    timing = pd.read_csv(DATA / "quarter_timing.csv", parse_dates=["report_date", "latest_filing_date", "quarter_effective_date", "next_quarter_effective_date"])
    copy_exact(LATEST / "calendar.parquet", DATA / "calendar.parquet", sources)
    calendar = pd.read_parquet(DATA / "calendar.parquet", columns=["trade_date", "is_test"])
    all_sessions = pd.DatetimeIndex(sorted(set(prices.loc[prices.ticker.eq("QQQ"), "trade_date"]) | set(calendar.trade_date)))
    fifth_checks = []
    for row in timing.itertuples(index=False):
        after = all_sessions[all_sessions > row.latest_filing_date]
        if len(after) < 5 or after[4] != row.quarter_effective_date:
            raise ValueError(f"FIFTH_SESSION_EFFECTIVE_CLOCK_MISMATCH:{row.quarter}")
        fifth_checks.append({"quarter": row.quarter, "latest_filing_date": str(row.latest_filing_date.date()),
                             "effective_date": str(row.quarter_effective_date.date()), "fifth_following_session_matches": True})
    clock = {"pre2026": check_latest_effective(pre, timing, "active_13f_quarter")}

    # Only observed signal-time features and qualification metadata are read.
    # The test-price numeric columns are never loaded here.
    test_source = QUALIFIED / "test_features_context.parquet"
    sources[str(test_source.resolve())] = sha(test_source)
    test = pd.read_parquet(test_source)
    if len(test) != 62476 or test.duplicated(KEY).any() or not test.signal_date.dt.year.eq(2026).all():
        raise ValueError("TEST_CONTEXT_CONTRACT_MISMATCH")
    if not np.isfinite(test[FEATURES].to_numpy(float)).all():
        raise ValueError("NONFINITE_QUALIFIED_TEST_FEATURE")
    candidates = test.loc[test.new_buy_eligible].copy()
    if len(candidates) != 62393 or int((~test.new_buy_eligible).sum()) != 83:
        raise ValueError("TEST_NEW_BUY_OR_HELD_ONLY_CONTRACT_MISMATCH")
    clock["qualified2026"] = check_latest_effective(candidates, timing, "quarter")
    test["known_input_conflict"] = test.ticker.eq("GLW") & test.signal_date.eq(pd.Timestamp("2026-02-26"))
    test["input_scope"] = np.where(test.new_buy_eligible, "qualified_current_pool_research_only", "context_only_if_held")
    test.to_parquet(DATA / "test_panel.parquet", index=False)
    candidates = test.loc[test.new_buy_eligible].copy()
    candidates.to_parquet(DATA / "test_candidates.parquet", index=False)
    copy_exact(QUALIFIED / "test_prices.parquet", DATA / "test_prices.parquet", sources)
    price_metadata = pq.ParquetFile(DATA / "test_prices.parquet")
    if price_metadata.metadata.num_rows != 211482:
        raise ValueError("TEST_PRICE_BYTE_COPY_ROW_COUNT_MISMATCH")
    copy_exact(QUALIFIED / "operational_exit_evidence.csv", DATA / "operational_exit_evidence.csv", sources)
    copy_exact(INVENTORY, DATA / "full_candidate_gate.parquet", sources)
    full = pd.read_parquet(DATA / "full_candidate_gate.parquet")
    if len(full) != 111868 or full.duplicated(KEY).any():
        raise ValueError("FULL_TEST_CANDIDATE_KEY_CONTRACT_MISMATCH")
    clock["all2026_candidate_keys"] = check_latest_effective(full, timing, "quarter")
    counts = full.current_frozen_status.value_counts().to_dict()
    if counts != {"QUALIFIED": 62393, "UNKNOWN": 47271, "PROVEN_INELIGIBLE": 2204}:
        raise ValueError("FULL_CANDIDATE_STATUS_CONTRACT_MISMATCH")
    qualified_keys = full.loc[full.current_frozen_status.eq("QUALIFIED"), KEY].sort_values(KEY).reset_index(drop=True)
    pd.testing.assert_frame_equal(qualified_keys, candidates[KEY].sort_values(KEY).reset_index(drop=True), check_dtype=False)
    availability = full[KEY + ["quarter", "current_frozen_status", "current_reason", "final_input_gate", "glw_known_conflict_outside_frozen_gate"]].copy()
    availability["prediction_available"] = availability.current_frozen_status.eq("QUALIFIED")
    availability["unavailable_reason"] = availability.current_reason.where(~availability.prediction_available, "")
    availability.to_parquet(DATA / "full_candidate_availability.parquet", index=False)
    coverage = full.groupby(["signal_date", "quarter"]).current_frozen_status.value_counts().unstack(fill_value=0).reset_index()
    if not coverage.UNKNOWN.gt(0).all():
        raise ValueError("FROZEN_UNKNOWN_COVERAGE_EXPECTATION_CHANGED")
    coverage.to_csv(DATA / "candidate_coverage.csv", index=False)

    # Bind source construction evidence separately from the learning matrix.
    evidence_paths = [LATEST / "JOINT_DATA_AUDIT.json", QUALIFIED / "DATA_RECEIPT.json", QUALIFIED / "DATA_FREEZE.json",
                      WS / "a2_top20_multimodel_selection_20260928_9231/acceptance_diagnostics/evidence/PRE_UNIVERSE_SELECTION.json",
                      ORIGINAL / "universe/quarterly_universe_manifest.parquet",
                      ORIGINAL / "universe/quarterly_universe_members.parquet",
                      ORIGINAL / "universe/selected_top100_24_manager.parquet",
                      ORIGINAL / "audit/manager_quarter_source_evidence.parquet"]
    for path in evidence_paths:
        sources[str(path.resolve())] = sha(path)
    materialized = STRICT / "test2026_stage/identity_feature_application_r1/ORIGINAL_32_FEATURES_2026_CANDIDATE_INPUT_ONLY.parquet"
    sources[str(materialized.resolve())] = sha(materialized)
    mat_metadata = pq.ParquetFile(materialized)
    selection = json.loads(evidence_paths[3].read_text(encoding="utf-8"))

    audit = {
        "status": "PASS_AVAILABLE_INPUT_CONTRACT_WITH_BLOCKED_FORMAL_FULL_POOL",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_data_modified": False, "model_fit_calls": 0, "model_predict_calls": 0,
        "account_result_files_read": False, "numeric_2026_price_columns_read": False,
        "full_pool_formal_status": "BLOCKED_DATA", "qualified_research_replay_ready": True,
        "pool_rule": {
            "id": "original_top100_24_union", "original_manager_count": 24,
            "selection": "Original frozen eligible top100 holdings per original manager and reporting quarter, unioned by security identity; existing quarterly membership, deduplication, cap, mapping and 121-session availability controls are inherited, not rebuilt or silently relaxed.",
            "timing": "Use latest publicly filed and effective quarter; all 24 managers' latest actual filing date plus fifth following US equity session; carry preceding quarter until successor effective.",
            "current_available_pool_is_raw_13f_union": False,
            "top20_selection_scope": "Every current qualified candidate is scored; no filter to old A2 TOP20.",
            "quarter_clock_checks": clock, "fifth_session_checks": fifth_checks,
            "pre2026_selection_effects": selection,
        },
        "pre2026": {
            "rows": len(pre), "signal_days": int(pre.signal_date.nunique()),
            "first_signal": str(pre.signal_date.min().date()), "last_signal": str(pre.signal_date.max().date()),
            "features": FEATURES, "feature_count": 32, "training_exclusive_boundary": "2026-01-01",
            "physical_pre_price_rows": len(prices), "last_pre_price": str(prices.trade_date.max().date()),
            "label": "following QQQ-session open / next QQQ-session open - 1; uncosted one-session affine index return",
            "label_audit": label_audit,
            "mature_fold_rows": {c: int((pre.signal_date.lt(c) & pre.label_end_date.lt(c) & pre.label_available & pre.new_buy_eligible).sum())
                                 for c in ["2024-01-01", "2025-01-01", "2026-01-01"]},
            "volatility_target_column": "y_abs_next_open",
            "volatility_target_semantics": "Absolute raw one-session next-open index return, defined only for available matured labels. A conditional absolute-return scale proxy, not multi-session realized volatility or a directly observed conditional standard deviation.",
            "target_clipping_by_input_builder": False,
        },
        "test2026": {
            "full_candidate_keys": len(full), "qualified_current_candidates": len(candidates), "held_only_context_rows": 83,
            "unknown_rows": 47271, "proven_ineligible_rows": 2204, "complete_candidate_days": 0,
            "unknown_reason_counts": full.loc[full.current_frozen_status.eq("UNKNOWN"), "current_reason"].value_counts().to_dict(),
            "unknown_prediction_available": False, "unknown_promoted": 0,
            "test_price_byte_copy_rows": int(price_metadata.metadata.num_rows),
            "full_feature_materialization_metadata_only": {"path": str(materialized.resolve()), "rows": mat_metadata.metadata.num_rows,
                                                           "included_in_training": False, "numeric_columns_read_by_builder": False},
            "first_signal": str(candidates.signal_date.min().date()), "last_signal": str(candidates.signal_date.max().date()),
            "terminal_valuation_date": "2026-09-24", "full_calendar_year": False,
            "previously_exposed": True, "blind_test": False,
            "known_input_conflict": "GLW 2026-02-26 issuer/vendor event-date conflict is retained as explicit diagnostic qualification; zero target or certified NAV does not remove input dependence.",
            "numeric_price_load_rule": "Load these test-price columns only in evaluation after the whole batch is frozen; never fit, calibrate or select on 2026.",
        },
        "pit_limitations": [
            "Original manager-set selection and historical identity/transport availability dates are not independently established.",
            "Pre2026 already excludes missing frozen prices and insufficient 121-session histories; this does not eliminate availability or survivorship bias.",
            "Historical vendor actual arrival timestamps and later revisions of earlier raw prices/corporate-action records remain unproven.",
            "Affine price-index units are not raw tradable shares or certified shareholder total return.",
            "Complete 2026 candidate keys exist, but every day still contains UNKNOWN inputs; qualified research replay cannot certify full-pool TOP20.",
            "2025 and 2026 have prior exposure; recomputing with pre2026 learning does not recreate an untouched holdout.",
        ],
        "source_sha256": sources,
    }
    save_json(AUDITS / "INPUT_AUDIT.json", audit)
    outputs = {str(path.resolve()): sha(path) for path in sorted(DATA.iterdir()) if path.is_file()}
    outputs[str((AUDITS / "INPUT_AUDIT.json").resolve())] = sha(AUDITS / "INPUT_AUDIT.json")
    bindings = {
        "schema_version": 1, "batch": ROOT.name,
        "pre_panel": str((DATA / "pre_panel.parquet").resolve()), "pre_prices": str((DATA / "pre_prices.parquet").resolve()),
        "test_panel": str((DATA / "test_panel.parquet").resolve()), "test_candidates": str((DATA / "test_candidates.parquet").resolve()),
        "test_prices": str((DATA / "test_prices.parquet").resolve()), "calendar": str((DATA / "calendar.parquet").resolve()),
        "quarter_timing": str((DATA / "quarter_timing.csv").resolve()), "full_gate": str((DATA / "full_candidate_gate.parquet").resolve()),
        "full_availability": str((DATA / "full_candidate_availability.parquet").resolve()), "ops": str((DATA / "operational_exit_evidence.csv").resolve()),
        "coverage": str((DATA / "candidate_coverage.csv").resolve()), "input_audit": str((AUDITS / "INPUT_AUDIT.json").resolve()),
        "features": FEATURES, "return_target": "y_next_open", "volatility_target": "y_abs_next_open",
        "full_pool_formal_status": "BLOCKED_DATA", "source_sha256": sources, "output_sha256": outputs,
        "test_price_load_requires_batch_freeze": True,
    }
    # Verify original bytes stayed intact throughout preparation.
    for path, digest in sources.items():
        if sha(Path(path)) != digest:
            raise ValueError(f"SOURCE_CHANGED_DURING_BUILD:{path}")
    save_json(ROOT / "input_paths.json", bindings)
    print(json.dumps({"status": audit["status"], "pre_rows": len(pre), "test_candidates": len(candidates),
                      "full_candidate_keys": len(full), "formal_full_pool": "BLOCKED_DATA",
                      "numeric_2026_price_columns_read": False}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    verify_existing() if args.verify else build()
