"""Compact final summary after correcting evidence-only cash event gates."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "test2026_stage/r6_contract_correction"
R5 = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results\test2026\evidence_continuation_20260927_r5")
KEY = ["cusip", "title_of_class", "quarter", "signal_date"]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def key_sha(frame: pd.DataFrame) -> str:
    keys = frame[KEY].sort_values(KEY, kind="mergesort")
    return hashlib.sha256(pd.util.hash_pandas_object(keys, index=False).to_numpy().tobytes()).hexdigest()


def main() -> None:
    parent = R5 / "R5_FINAL_CANDIDATE_INPUT_GATE.parquet"
    assert sha(parent) == "1e14e19edf5ca01a097f1b2b2955e45e3b0e5831782d49ea6e5508053985e42a"
    final = OUT / "R6_FULL_CANDIDATE_INPUT_GATE.parquet"
    ledger = pd.read_parquet(final)
    before = pd.read_parquet(parent, columns=KEY + ["final_input_gate"])
    assert len(ledger) == len(before) == 111868
    assert not ledger.duplicated(KEY).any() and not before.duplicated(KEY).any()
    assert key_sha(ledger) == key_sha(before) == "0f4167d679f1e38b94ffff6488088ad27a6fa6ea1dfd84aa63f8308ae17f96d1"
    assert ledger.signal_date.nunique() == 181
    assert ledger.quarter.value_counts().sort_index().to_dict() == {
        "2025Q3": 23148, "2025Q4": 38064, "2026Q1": 38006, "2026Q2": 12650}
    compare = ledger[KEY + ["final_input_gate"]].merge(before, on=KEY, validate="one_to_one",
                                                       suffixes=("_r6", "_r5"))
    changed = compare.final_input_gate_r6.ne(compare.final_input_gate_r5)
    assert int(changed.sum()) == 1096
    assert compare.loc[changed, "final_input_gate_r5"].eq("UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME").all()
    assert compare.loc[changed, "final_input_gate_r6"].eq("INPUT_VERIFIED_THIS_GATE").all()
    unknown = ledger.final_input_gate.str.startswith("UNKNOWN_")
    verified = ledger.final_input_gate.str.startswith("INPUT_VERIFIED")
    ineligible = ledger.final_input_gate.str.startswith("PROVEN_")
    assert (int(verified.sum()), int(ineligible.sum()), int(unknown.sum())) == (61963, 2204, 47701)
    cols = KEY + ["ticker", "moomoo_transport_code", "final_input_gate", "feature_error",
                  "first_consumed_2026_event", "first_unexplained_2026_jump",
                  "coordinate_evidence_class", "2026_event_publication_time_unverified",
                  "no_frozen_coordinate_overlap", "unexplained_raw_jump_dependency",
                  "multi_cusip_transport_interval_pending", "lookback_121_eligible",
                  "has_32_finite", "version_checked"]
    ledger.loc[unknown, cols].to_parquet(OUT / "R6_REMAINING_CANDIDATE_GAPS.parquet", index=False)
    ledger.groupby(["quarter", "final_input_gate"]).size().rename("candidate_days").reset_index().to_csv(
        OUT / "R6_QUARTER_GATE_SUMMARY.csv", index=False)
    ledger.groupby(["signal_date", "final_input_gate"]).size().rename("candidate_days").reset_index().to_csv(
        OUT / "R6_SIGNAL_DATE_GATE_SUMMARY.csv", index=False)
    summary = {"status": "COMMON_CANDIDATE_GATE_INCOMPLETE_AFTER_ORIGINAL_CONTRACT_CORRECTION",
               "candidate_days": 111868, "signal_days": 181,
               "candidate_key_fingerprint_sha256": key_sha(ledger),
               "parent_r5_sha256": sha(parent), "r6_final_sha256": sha(final),
               "new_verified_ten_cash_events": 585, "new_verified_four_single_events": 511,
               "new_verified_total": int(changed.sum()),
               "verified": int(verified.sum()), "proven_ineligible": int(ineligible.sum()),
               "remaining_unknown": int(unknown.sum()),
               "main_status_counts": ledger.final_input_gate.value_counts().to_dict(),
               "test_asof_utc": "2026-09-25T18:10:21.6494935Z",
               "last_signal": "2026-09-22", "last_execution": "2026-09-23",
               "terminal_valuation": "2026-09-24",
               "four_frozen_model_objects_loaded": 0,
               "four_frozen_model_fit_calls": 0, "preprocessor_fit_calls_in_test2026": 0,
               "formal_predictions": 0, "formal_accounting_replays": 0,
               "separate_new_method_training": "not part of this fixed four-model test ledger"}
    (OUT / "R6_GATE_SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", "utf-8")
    print(json.dumps({"verified": summary["verified"], "unknown": summary["remaining_unknown"]}))


if __name__ == "__main__":
    main()
