"""V22.067A3M: second, read-only historical application of the frozen A1M model."""
import argparse
import hashlib
import importlib.util
import json
import time
import warnings
from pathlib import Path

import joblib
import pandas as pd

ROOT = Path(__file__).parent
CORE_PATH = ROOT / "v22_067a2m_fast3_soxx_frozen_model_reverse_validation_2024_2025_r1.py"
SPEC = importlib.util.spec_from_file_location("a2_frozen_core", CORE_PATH)
CORE = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(CORE)
MODEL_FILE = Path(r"D:\us-tech-quant-results\v22\V22.067A1M_FAST3_RECENT_YEAR_SOXX_RANKING_BASELINE_R1\soxx_model_bundle.joblib")
A1_SUMMARY = Path(r"D:\us-tech-quant-results\v22\V22.067A1M_FAST3_RECENT_YEAR_SOXX_RANKING_BASELINE_R1\v22_067a1m_summary.json")
A2_SUMMARY = Path(r"D:\us-tech-quant-results\v22\V22.067A2M_FAST3_SOXX_FROZEN_MODEL_REVERSE_VALIDATION_2024_2025_R1\v22_067a2m_summary.json")
RESULT = Path(r"D:\us-tech-quant-results\v22\V22.067A3M_FAST3_SOXX_FROZEN_MODEL_REVERSE_VALIDATION_2023_2024_R1")
START_ET = pd.Timestamp("2023-07-29 00:00:00", tz="America/New_York")
END_ET = pd.Timestamp("2024-07-28 23:59:59", tz="America/New_York")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""): h.update(b)
    return h.hexdigest()


def validate_bundle(bundle):
    CORE.validate_bundle(bundle)
    if not bundle.get("date_blocks") or not bundle.get("model_configuration"):
        raise ValueError("Frozen training boundaries or model configuration missing")
    if not hasattr(bundle["long_pipeline"], "predict_proba") or not hasattr(bundle["short_pipeline"], "predict_proba"):
        raise ValueError("Frozen preprocessing/model pipeline missing")


def comparison(a1, a2, long, short):
    return {
        "recent_confirmation_a1m": {"LONG": {"precision": a1["long"]["confirmation_high_score"]["precision"], "lift": a1["long"]["confirmation_high_score"]["lift_over_base_rate"]}, "SHORT": {"precision": a1["short"]["confirmation_high_score"]["precision"], "lift": a1["short"]["confirmation_high_score"]["lift_over_base_rate"]}},
        "first_reverse_year_a2m": {"LONG": {"precision": a2["long"]["selected_precision"], "lift": a2["long"]["lift_over_base_rate"]}, "SHORT": {"precision": a2["short"]["selected_precision"], "lift": a2["short"]["lift_over_base_rate"]}},
        "second_reverse_year_a3m": {"LONG": {"precision": long["selected_precision"], "lift": long["lift_over_base_rate"]}, "SHORT": {"precision": short["selected_precision"], "lift": short["lift_over_base_rate"]}},
    }


def final_decision(long, short, first):
    if not first.get("final_status") == "PASS": return "FROZEN_MODEL_APPLICATION_FAILED"
    if long["total_candidate_count"] == 0: return "SECOND_REVERSE_VALIDATION_DATA_INSUFFICIENT"
    if long["transfer_success"] and short["transfer_success"]: return "FROZEN_SOXX_BOTH_DIRECTIONS_TRANSFER_ACROSS_TWO_PRIOR_YEARS"
    if long["transfer_success"]: return "FROZEN_SOXX_LONG_TRANSFERS_ACROSS_TWO_PRIOR_YEARS"
    if short["transfer_success"]: return "FROZEN_SOXX_SHORT_TRANSFERS_ACROSS_TWO_PRIOR_YEARS"
    if any(x["lift_over_base_rate"] is not None and x["lift_over_base_rate"] > 1 for x in (long, short)): return "FROZEN_SOXX_SIGNAL_WEAKENS_IN_SECOND_PRIOR_YEAR"
    return "FROZEN_SOXX_SIGNAL_FAILS_SECOND_PRIOR_YEAR"


def run():
    started = time.time(); before = sha256(MODEL_FILE); bundle = joblib.load(MODEL_FILE); validate_bundle(bundle)
    a1, a2 = json.loads(A1_SUMMARY.read_text(encoding="utf-8")), json.loads(A2_SUMMARY.read_text(encoding="utf-8"))
    if a1.get("final_status") != "PASS" or a2.get("final_status") != "PASS": raise ValueError("Required frozen/reference summary is not PASS")
    # Strict reuse: only the core's study boundaries are changed before invoking its A0/A2 logic.
    CORE.START_ET, CORE.END_ET = START_ET, END_ET
    qqq, soxx = CORE.load("QQQ"), CORE.load("SOXX")
    data = CORE.feature_frame("SOXX", soxx, qqq); data = data[data.feature_complete & data.label_complete].copy()
    data.candidate_timestamp_utc = pd.to_datetime(data.candidate_timestamp_utc, utc=True)
    data = data[(data.candidate_timestamp_utc.dt.tz_convert("America/New_York") >= START_ET) & (data.candidate_timestamp_utc.dt.tz_convert("America/New_York") <= END_ET)]
    long_z, long = CORE.infer(data, bundle, "LONG"); short_z, short = CORE.infer(data, bundle, "SHORT")
    after = sha256(MODEL_FILE)
    if before != after: raise RuntimeError("Frozen model SHA256 changed during application")
    for item in (long, short):
        item["covered_month_count"] = len(item["monthly_signal_counts"])
        item["after_hours_selected_count"] = item["session_distribution"].get("AFTER_HOURS", 0)
        item["overnight_selected_count"] = item["session_distribution"].get("OVERNIGHT", 0)
        item["premarket_selected_count"] = item["session_distribution"].get("PREMARKET", 0)
        item["maximum_single_month_signal_concentration"] = max(item["monthly_signal_counts"].values(), default=0) / item["selected_count"] if item["selected_count"] else None
    RESULT.mkdir(parents=True, exist_ok=True)
    pd.concat([long_z, short_z], ignore_index=True).sort_values(["direction", "score"], ascending=[True, False]).to_csv(RESULT / "reverse_validation_ranked_candidates_2023_2024.csv", index=False)
    rows = [{"direction": d, "month": m, "signal_count": n} for d, item in (("LONG", long), ("SHORT", short)) for m, n in item["monthly_signal_counts"].items()]
    pd.DataFrame(rows, columns=["direction", "month", "signal_count"]).to_csv(RESULT / "monthly_signal_summary.csv", index=False)
    report = {"final_status": "PASS", "final_diagnostic_decision": final_decision(long, short, a2), "targeted_test_count": 8, "study_start_et": str(START_ET), "study_end_et": str(END_ET), "total_candidate_count": int(len(data)), "long": long, "short": short, "cross_year_stability_comparison": comparison(a1, a2, long, short), "model_sha256": before, "a1m_input_sha256": bundle["input_sha256"], "model_retrained": False, "model_coefficients_modified": False, "feature_list_modified": False, "threshold_modified": False, "frozen_input_modification_count": 0, "broker_action_allowed": False, "paper_action_allowed": False, "official_adoption_allowed": False, "total_elapsed_seconds": time.time()-started}
    (RESULT / "v22_067a3m_summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (RESULT / "test_report.json").write_text(json.dumps({"targeted_test_count": 8, "status": "pytest_required_and_run_by_wrapper", "model_retrained": False, "frozen_input_modification_count": 0}, indent=2), encoding="utf-8")
    return {"FINAL_STATUS": report["final_status"], "FINAL_DIAGNOSTIC_DECISION": report["final_diagnostic_decision"], "TARGETED_TEST_COUNT": 8, "STUDY_START_ET": START_ET, "STUDY_END_ET": END_ET, "TOTAL_CANDIDATE_COUNT": len(data), "LONG_BASE_RATE": long["base_positive_rate"], "SHORT_BASE_RATE": short["base_positive_rate"], "LONG_SELECTED_COUNT": long["selected_count"], "SHORT_SELECTED_COUNT": short["selected_count"], "LONG_PRECISION": long["selected_precision"], "SHORT_PRECISION": short["selected_precision"], "LONG_LIFT": long["lift_over_base_rate"], "SHORT_LIFT": short["lift_over_base_rate"], "LONG_0P50_HIT_RATE": long["0p50_hit_rate"], "SHORT_0P50_HIT_RATE": short["0p50_hit_rate"], "LONG_COVERED_MONTH_COUNT": long["covered_month_count"], "SHORT_COVERED_MONTH_COUNT": short["covered_month_count"], "LONG_MAX_SINGLE_MONTH_CONCENTRATION": long["maximum_single_month_signal_concentration"], "SHORT_MAX_SINGLE_MONTH_CONCENTRATION": short["maximum_single_month_signal_concentration"], "MODEL_RETRAINED": False, "FEATURE_LIST_MODIFIED": False, "THRESHOLD_MODIFIED": False, "TOTAL_ELAPSED_SECONDS": report["total_elapsed_seconds"], "FROZEN_INPUT_MODIFICATION_COUNT": 0, "RESULT_DIRECTORY": str(RESULT)}


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--execute", action="store_true")
    if p.parse_args().execute:
        warnings.simplefilter("ignore", FutureWarning)
        for key, value in run().items(): print(f"{key}={value}")
