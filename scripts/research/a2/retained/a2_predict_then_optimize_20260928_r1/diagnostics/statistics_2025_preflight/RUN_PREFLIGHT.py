"""2025-only real integration audit; writes only this diagnostic directory."""
from __future__ import annotations

import sys
import time
import traceback
import threading
from pathlib import Path
from datetime import datetime, timezone

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
COUNTS = {"evaluation_2025_file_opens": 0, "evaluation_2026_account_file_opens": 0}
LOCK = threading.Lock()


def path_guard(event, args):
    if event != "open" or not args or not isinstance(args[0], (str, bytes, Path)):
        return
    raw = args[0].decode() if isinstance(args[0], bytes) else str(args[0])
    parts = raw.replace("\\", "/").lower().split("/")
    if "evaluation_2026" in parts or "evaluation_controls_2026" in parts:
        raise RuntimeError("UNFINISHED_2026_ACCOUNT_READ_FORBIDDEN")
    if "evaluation_2025" in parts:
        with LOCK:
            COUNTS["evaluation_2025_file_opens"] += 1


sys.addaudithook(path_guard)

import numpy as np
import pandas as pd
from common import sha, write, read, strategies, forecasts, RISKS, OPTIMIZERS, COALITIONS, FUSIONS
from freeze_batch import validate_global_freeze
from comparison_analysis import analyze_year, METRICS


def require(condition, reason):
    if not condition:
        raise AssertionError(reason)


def missing_numeric(frame):
    return {name: int((~np.isfinite(frame[name].to_numpy(float))).sum())
            for name in frame.select_dtypes(include=[np.number]).columns
            if (~np.isfinite(frame[name].to_numpy(float))).any()}


def peak_working_set_mb():
    try:
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ["PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage"]]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return counters.PeakWorkingSetSize / 1024 ** 2
    except Exception:
        pass
    return None


def main():
    started = time.perf_counter()
    receipt = {"created_utc": datetime.now(timezone.utc).isoformat(), "year": 2025,
               "fit_calls": 0, "statistics_source_modified": False, "frozen_artifacts_modified": False,
               "unfinished_2026_account_reads": 0, "source_sha256": {name: sha(ROOT / name)
               for name in ["comparison_analysis.py", "common.py", "freeze_batch.py"]},
               "runner_sha256": sha(Path(__file__))}
    prior = OUT / "PREFLIGHT_RECEIPT_FAILED_LEFT_RIGHT_ARGUMENTS.json"
    if prior.is_file():
        receipt["prior_failed_preflight"] = {"path": str(prior.relative_to(ROOT)), "sha256": sha(prior),
            "error": read(prior).get("error"), "statistics_fix": "DataFrame parameters renamed left_frame/right_frame; result labels stay left/right; no learning or execution change"}
    try:
        freeze = validate_global_freeze()
        receipt["global_freeze_sha256"] = sha(ROOT / "GLOBAL_FREEZE.json")
        receipt["global_frozen_files_verified_before_analysis"] = len(freeze["artifact_sha256"])
        print("GLOBAL_FREEZE_HASHES_VERIFIED; starting 2025 analyze_year", flush=True)
        rows, daily = analyze_year(2025, OUT)
        roster = pd.DataFrame(strategies())
        require(len(rows) == 5053 and rows.strategy_id.is_unique, "2025_ROSTER_SIZE_OR_DUPLICATE")
        require(rows.status.eq("REPLAY_COMPLETE").all(), "2025_NOT_ALL_COMPLETE")
        require(set(rows.strategy_id) == set(roster.strategy_id), "2025_STRATEGY_SET_DRIFT")
        for name in ["forecast_id", "coalition", "fusion", "risk", "optimizer", "route", "target_fusion"]:
            wanted = roster.set_index("strategy_id")[name].fillna("none").astype(str)
            actual = rows.set_index("strategy_id")[name].fillna("none").astype(str)
            require(actual.reindex(wanted.index).equals(wanted), "2025_FACTOR_METADATA_DRIFT:" + name)
        calendar = pd.DatetimeIndex(pd.read_parquet(ROOT / "input/eval_2025/calendar.parquet", columns=["trade_date"]).trade_date)
        require(daily.index.equals(calendar) and daily.columns.is_unique, "2025_DAILY_INDEX_OR_COLUMN_DRIFT")
        require(set(daily.columns) == set(rows.strategy_id), "2025_DAILY_ACCOUNT_SET_DRIFT")
        daily_finite = np.isfinite(daily.to_numpy(float))
        receipt["daily_returns"] = {"calendar_rows": len(daily), "accounts": len(daily.columns),
            "first_row_nonfinite_returns": int((~daily_finite[0]).sum()),
            "internal_nonfinite_returns": int((~daily_finite[1:]).sum()),
            "accounts_with_internal_nonfinite_returns": int((~daily_finite[1:]).any(axis=0).sum()),
            "whole_roster_common_valid_days": int(daily_finite.all(axis=1).sum())}
        require((~daily_finite[0]).all(), "FIRST_ROW_MUST_NOT_INVENT_PREWINDOW_NAV_RETURN")

        matched = pd.read_csv(OUT / "matched_dimension_comparisons_2025.csv")
        expected_types = {"risk": 45, "optimizer": 3, "single_predictor": 465,
                          "fusion_within_fixed_members": 110, "target_vs_prediction_fusion": 11}
        require(len(matched) == 634 and matched.comparison.value_counts().to_dict() == expected_types,
                "2025_MATCHED_COMPARISON_COUNT_OR_TYPE")
        matched_keys = matched[["comparison", "coalition", "left", "right"]].fillna("")
        require(not matched_keys.duplicated().any(), "2025_DUPLICATE_MATCHED_COMPARISON")
        expected_cells = {"risk": 456, "optimizer": 1520, "single_predictor": 30,
                          "fusion_within_fixed_members": 30, "target_vs_prediction_fusion": 30}
        require(matched.expected_cells.eq(matched.comparison.map(expected_cells)).all(), "EXPECTED_PAIRED_CELL_DRIFT")
        require(matched.matched_cells.eq(matched.expected_cells).all() and matched.complete_matched_grid.all(),
                "2025_FULL_ROSTER_HAS_UNMATCHED_CELLS")
        require(matched[["left_only_success_cells", "right_only_success_cells", "both_missing_cells"]].eq(0).all().all(),
                "2025_MISSING_PAIRED_CELLS")
        require(matched.days.eq(matched.common_valid_return_days).all(), "HAC_N_NOT_SHARED_VALID_DAYS")
        require(matched.paired_cells_are_not_independent_samples.all(), "PAIRED_SAMPLE_INDEPENDENCE_DRIFT")
        for row in matched.itertuples():
            import json
            left_ids, right_ids = json.loads(row.left_ids_json), json.loads(row.right_ids_json)
            require(len(left_ids) == len(right_ids) == row.matched_cells, "PAIRED_ID_COUNT_DRIFT")
            require(len(set(left_ids)) == len(left_ids) and len(set(right_ids)) == len(right_ids), "DUPLICATE_PAIRED_STRATEGY")
        receipt["matched_comparisons"] = {"rows": len(matched), "types": expected_types,
            "all_cells_complete": True, "min_valid_days": int(matched.days.min()), "max_valid_days": int(matched.days.max()),
            "numeric_nonfinite_counts": missing_numeric(matched)}

        conditional = pd.read_csv(OUT / "fusion_risk_conditional_comparisons_2025.csv")
        require(len(conditional) == 1100, "2025_CONDITIONAL_FUSION_COUNT")
        require(not conditional[["coalition", "left", "right", "risk"]].duplicated().any(), "CONDITIONAL_FUSION_DUPLICATE")
        require(conditional.matched_cells.eq(3).all() and conditional.expected_cells.eq(3).all(), "CONDITIONAL_FUSION_CELL_COUNT")
        require(conditional.complete_matched_grid.all(), "CONDITIONAL_FUSION_MISSING_CELL")
        receipt["conditional_fusion_comparisons"] = {"rows": len(conditional), "matched_optimizer_cells_per_row": 3,
            "numeric_nonfinite_counts": missing_numeric(conditional)}

        factors = {}
        for metric in ["net_return", "max_drawdown", "mean_gross_exposure", "mean_daily_log_return"]:
            factor = pd.read_csv(OUT / f"factor_interactions_2025_{metric}.csv")
            require(len(factor) == 4560 and not factor[["forecast_id", "risk", "optimizer"]].duplicated().any(), "FACTOR_SIZE_OR_DUPLICATE:" + metric)
            expected = {(f["forecast_id"], r, o) for f in forecasts() for r in RISKS for o in OPTIMIZERS}
            require(set(zip(factor.forecast_id, factor.risk, factor.optimizer)) == expected, "FACTOR_CARTESIAN_DRIFT:" + metric)
            effect_columns = ["grand_mean", "forecast_main", "risk_main", "optimizer_main", "forecast_risk_interaction",
                              "forecast_optimizer_interaction", "risk_optimizer_interaction", "three_way_interaction"]
            require(np.isfinite(factor[["observed", *effect_columns]].to_numpy(float)).all(), "NONFINITE_FACTOR:" + metric)
            residual = float(np.abs(factor[effect_columns].sum(axis=1) - factor.observed).max())
            require(residual <= 1e-12, "FACTOR_RECONSTRUCTION_DRIFT:" + metric)
            factors[metric] = {"rows": len(factor), "max_reconstruction_error": residual,
                               "numeric_nonfinite_counts": missing_numeric(factor)}
        receipt["factor_decompositions"] = factors

        adjusted = pd.read_csv(OUT / "optimization_vs_fixed_gross_2025.csv")
        expected_adjusted = roster.loc[roster.optimizer.isin(OPTIMIZERS)]
        expected_count = len(expected_adjusted)
        require(expected_count == 4890 == 4560 + 330, "FROZEN_BUDGET_CONTROL_ARITHMETIC")
        require(len(adjusted) == expected_count and adjusted.strategy_id.is_unique, "BUDGET_PAIRED_COUNT_OR_DUPLICATE")
        require(set(adjusted.strategy_id) == set(expected_adjusted.strategy_id), "BUDGET_PAIRED_STRATEGY_SET_DRIFT")
        require(adjusted.optimizer_fixed_gross.eq("equal_top20").all() and adjusted.risk_fixed_gross.eq("none").all(), "BUDGET_CONTROL_NOT_CANONICAL")
        control_spec = roster.set_index("strategy_id").loc[adjusted.strategy_id_fixed_gross]
        require(np.array_equal(adjusted.route.to_numpy(), control_spec.route.to_numpy()) and
                np.array_equal(adjusted.forecast_id.to_numpy(), control_spec.forecast_id.to_numpy()), "BUDGET_CONTROL_ROUTE_OR_FORECAST_MISMATCH")
        delta_errors = {}
        for metric in METRICS:
            residual = adjusted["delta_" + metric] - (adjusted[metric] - adjusted[metric + "_fixed_gross"])
            delta_errors[metric] = float(residual.abs().max())
            require(delta_errors[metric] <= 1e-10, "BUDGET_CONTROL_DELTA_DRIFT:" + metric)
        receipt["optimization_vs_budget_control"] = {"rows": len(adjusted),
            "prediction_route_rows": int(adjusted.route.eq("prediction_fusion").sum()),
            "target_route_rows": int(adjusted.route.eq("target_fusion").sum()),
            "distinct_budget_controls": int(adjusted.strategy_id_fixed_gross.nunique()),
            "count_correction": "4890 = 4560 + 330; 4590 was a request arithmetic typo, no roster change",
            "delta_reconstruction_max_errors": delta_errors, "numeric_nonfinite_counts": missing_numeric(adjusted)}
        receipt["rows_numeric_nonfinite_counts"] = missing_numeric(rows)
        receipt["roster_paths"] = len(rows)
        receipt["failed_paths"] = int(rows.status.ne("REPLAY_COMPLETE").sum())
        require(receipt["source_sha256"] == {name: sha(ROOT / name) for name in receipt["source_sha256"]}, "STATISTICAL_SOURCE_CHANGED_DURING_PREFLIGHT")
        receipt["output_sha256"] = {str(path.relative_to(ROOT)): sha(path) for path in OUT.iterdir() if path.suffix in [".csv", ".parquet"]}
        receipt["status"] = "PASS_2025_REAL_STATISTICAL_INTEGRATION"
    except Exception as error:
        receipt["status"] = "FAIL_2025_REAL_STATISTICAL_INTEGRATION"
        receipt["error_type"] = type(error).__name__
        receipt["error"] = str(error)
        receipt["traceback"] = traceback.format_exc()
    receipt["elapsed_seconds"] = time.perf_counter() - started
    receipt["peak_working_set_mb"] = peak_working_set_mb()
    receipt["file_open_audit"] = COUNTS
    write(OUT / "PREFLIGHT_RECEIPT.json", receipt)
    import json
    print(json.dumps({key: value for key, value in receipt.items() if key not in ["traceback", "output_sha256", "source_sha256"]}, ensure_ascii=False, default=str), flush=True)
    if not receipt["status"].startswith("PASS"):
        sys.exit(1)


if __name__ == "__main__":
    main()
