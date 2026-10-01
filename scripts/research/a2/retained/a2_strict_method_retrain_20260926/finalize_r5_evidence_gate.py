"""Validate the fixed candidate universe and emit compact r5 delta summaries."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "test2026_stage/r5_delta"
R4 = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results\test2026\evidence_continuation_20260926_r4\r4_continuation")
KEY = ["cusip", "title_of_class", "quarter", "signal_date"]


def key_digest(frame: pd.DataFrame) -> str:
    keys = frame[KEY].sort_values(KEY, kind="mergesort")
    return hashlib.sha256(pd.util.hash_pandas_object(keys, index=False).to_numpy().tobytes()).hexdigest()


def main() -> None:
    boundary = json.loads((OUT / "R5_IMMUTABLE_BOUNDARY.json").read_text("utf-8"))
    before = pd.read_parquet(R4 / "R4_FINAL_CANDIDATE_INPUT_GATE.parquet",
                             columns=KEY + ["final_input_gate"])
    after = pd.read_parquet(OUT / "R5_FINAL_CANDIDATE_INPUT_GATE.parquet")
    assert len(before) == len(after) == 111868
    assert not before.duplicated(KEY).any() and not after.duplicated(KEY).any()
    assert key_digest(before) == key_digest(after) == boundary["candidate_key_fingerprint_sha256"]
    assert after.signal_date.nunique() == boundary["signal_days"] == 181
    assert after.quarter.value_counts().sort_index().to_dict() == {
        "2025Q3": 23148, "2025Q4": 38064, "2026Q1": 38006, "2026Q2": 12650}
    comparison = after[KEY + ["final_input_gate"]].merge(before, on=KEY, validate="one_to_one",
                                                          suffixes=("_r5", "_r4"))
    changed = comparison.final_input_gate_r5.ne(comparison.final_input_gate_r4)
    assert int(changed.sum()) == 94
    assert comparison.loc[changed, "final_input_gate_r4"].eq(
        "UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME").all()
    assert comparison.loc[changed, "final_input_gate_r5"].eq("INPUT_VERIFIED_THIS_GATE").all()
    assert comparison.loc[changed, "cusip"].eq("146869102").all()
    assert comparison.loc[changed, "title_of_class"].eq("CL A").all()
    assert comparison.loc[changed, "signal_date"].ge("2026-05-08").all()
    unknown = after.final_input_gate.str.startswith("UNKNOWN_")
    verified = after.final_input_gate.str.startswith("INPUT_VERIFIED")
    ineligible = after.final_input_gate.str.startswith("PROVEN_")
    assert int(unknown.sum()) == 48797 and int(verified.sum()) == 60867 and int(ineligible.sum()) == 2204
    assert int(unknown.sum() + verified.sum() + ineligible.sum()) == 111868
    columns = KEY + ["ticker", "moomoo_transport_code", "final_input_gate", "feature_error",
                     "first_consumed_2026_event", "first_unexplained_2026_jump",
                     "coordinate_evidence_class", "2026_event_publication_time_unverified",
                     "no_frozen_coordinate_overlap", "unexplained_raw_jump_dependency",
                     "multi_cusip_transport_interval_pending", "lookback_121_eligible",
                     "has_32_finite", "version_checked"]
    after.loc[unknown, columns].to_parquet(OUT / "R5_REMAINING_CANDIDATE_GAPS.parquet", index=False)
    after.groupby(["quarter", "final_input_gate"]).size().rename("candidate_days").reset_index().to_csv(
        OUT / "R5_QUARTER_GATE_SUMMARY.csv", index=False)
    after.groupby(["signal_date", "final_input_gate"]).size().rename("candidate_days").reset_index().to_csv(
        OUT / "R5_SIGNAL_DATE_GATE_SUMMARY.csv", index=False)
    summary = {
        "status": "COMMON_CANDIDATE_INPUT_INCOMPLETE_NO_FROZEN_MODEL_PREDICTION",
        "candidate_days": 111868, "signal_days": 181,
        "candidate_key_fingerprint_sha256": key_digest(after),
        "r4_verified": 60773, "r4_proven_ineligible": 2204, "r4_unknown": 48891,
        "r5_verified": int(verified.sum()), "r5_proven_ineligible": int(ineligible.sum()),
        "r5_unknown": int(unknown.sum()), "new_verified": 94, "new_ineligible": 0,
        "main_status_counts": after.final_input_gate.value_counts().to_dict(),
        "formal_predictions": 0, "formal_accounting_replays": 0,
        "model_objects_loaded": 0, "new_model_fit_calls": 0,
        "new_preprocessor_fit_calls": 0,
        "test_asof_utc": boundary["test_asof_utc"],
        "last_signal": boundary["last_signal"], "last_execution": boundary["last_execution"],
        "terminal_valuation": boundary["terminal_valuation"],
    }
    (OUT / "R5_GATE_SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", "utf-8")
    print(json.dumps({"verified": summary["r5_verified"], "unknown": summary["r5_unknown"]}))


if __name__ == "__main__":
    main()
