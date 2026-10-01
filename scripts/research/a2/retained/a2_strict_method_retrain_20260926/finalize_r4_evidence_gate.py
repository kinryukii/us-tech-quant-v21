"""Summarize the additive r4 candidate decision ledger without running models."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent / "test2026_stage"
OUT = ROOT / "r4_continuation"
KEY = ["cusip", "title_of_class", "quarter", "signal_date"]
DEPENDENCIES = ["2026_event_publication_time_unverified", "no_frozen_coordinate_overlap",
                "unexplained_raw_jump_dependency", "multi_cusip_transport_interval_pending",
                "proven_lifecycle_ineligible", "proven_121_ineligible", "lookback_121_eligible",
                "has_32_finite", "version_checked"]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def key_digest(frame: pd.DataFrame) -> str:
    sorted_keys = frame[KEY].sort_values(KEY, kind="mergesort")
    return hashlib.sha256(pd.util.hash_pandas_object(sorted_keys, index=False).to_numpy().tobytes()).hexdigest()


def main() -> None:
    baseline = json.loads((ROOT / "r4_validation/R3_BASELINE_EXACT_KEY_AND_HASH.json").read_text("utf-8"))
    ledger_path = OUT / "R4_FINAL_CANDIDATE_INPUT_GATE.parquet"
    ledger = pd.read_parquet(ledger_path)
    assert len(ledger) == baseline["candidate_days"] == 111868
    assert not ledger.duplicated(KEY).any()
    assert key_digest(ledger) == baseline["candidate_key_fingerprint_sha256"]
    assert ledger.signal_date.nunique() == baseline["signals"] == 181
    assert ledger.quarter.value_counts().sort_index().to_dict() == baseline["quarter_rows"]
    counts = ledger.final_input_gate.value_counts().to_dict()
    verified = int(ledger.final_input_gate.str.startswith("INPUT_VERIFIED").sum())
    ineligible = int(ledger.final_input_gate.str.startswith("PROVEN_").sum())
    unknown = int(ledger.final_input_gate.str.startswith("UNKNOWN_").sum())
    assert verified + ineligible + unknown == len(ledger)
    assert not ledger.loc[ledger.final_input_gate.str.startswith("INPUT_VERIFIED"),
                          ["proven_lifecycle_ineligible", "proven_121_ineligible",
                           "2026_event_publication_time_unverified",
                           "unexplained_raw_jump_dependency", "multi_cusip_transport_interval_pending"]].any().any()
    independently_proven = ledger.final_input_gate.eq("INPUT_VERIFIED_INDEPENDENT_ORIGINAL_COORDINATE")
    assert ledger.loc[independently_proven, "no_frozen_coordinate_overlap"].all()
    assert ledger.loc[independently_proven, "coordinate_evidence_class"].eq(
        "INDEPENDENT_ORIGINAL_COORDINATE_NO_EVENT_OR_JUMP").all()
    assert not ledger.loc[ledger.final_input_gate.eq("INPUT_VERIFIED_THIS_GATE"),
                          "no_frozen_coordinate_overlap"].any()
    original_r3 = ledger.r3_final_input_gate.value_counts().to_dict()
    assert original_r3 == baseline["gate_counts"]

    transitions = ledger.loc[ledger.r3_final_input_gate.ne(ledger.final_input_gate),
                             KEY + ["ticker", "moomoo_transport_code", "r3_final_input_gate",
                                    "final_input_gate", "coordinate_evidence_class", "r4_identity_result",
                                    "r4_dependency_result", "r4_event_result", "r4_event_source_sha256"]]
    transitions.to_parquet(OUT / "R4_ALL_STATUS_TRANSITIONS.parquet", index=False)
    unknown_rows = ledger.loc[ledger.final_input_gate.str.startswith("UNKNOWN_"),
                              KEY + ["ticker", "moomoo_transport_code", "r3_final_input_gate", "final_input_gate",
                                     "feature_error", "first_consumed_2026_event", "first_unexplained_2026_jump",
                                     "coordinate_evidence_class", "first_trade_official", "r4_identity_result",
                                     "r4_event_result"] + DEPENDENCIES]
    unknown_rows.to_csv(OUT / "R4_REMAINING_CANDIDATE_GAPS.csv", index=False)
    quarter = ledger.groupby(["quarter", "final_input_gate"], dropna=False).size().rename("candidate_days").reset_index()
    quarter.to_csv(OUT / "R4_QUARTER_GATE_SUMMARY.csv", index=False)
    daily = ledger.groupby(["signal_date", "final_input_gate"], dropna=False).size().rename("candidate_days").reset_index()
    daily.to_csv(OUT / "R4_SIGNAL_DATE_GATE_SUMMARY.csv", index=False)
    transition_counts = transitions.groupby(["r3_final_input_gate", "final_input_gate"]).size().to_dict()
    summary = {
        "status": "INCOMPLETE_COMMON_CANDIDATE_INPUT_GATE_NO_MODEL_INFERENCE",
        "test_asof_utc": "2026-09-25T18:10:21.6494935Z",
        "signal_days": 181, "last_signal": "2026-09-22", "last_execution": "2026-09-23",
        "terminal_valuation": "2026-09-24", "candidate_days": len(ledger),
        "candidate_key_fingerprint_sha256": key_digest(ledger),
        "r3_ledger_sha256": baseline["r3_input_file_sha256"]["FINAL_111868_CANDIDATE_INPUT_GATE.parquet"],
        "r4_ledger_sha256": digest(ledger_path),
        "current_verified": verified, "current_proven_ineligible": ineligible,
        "current_unknown": unknown, "gate_counts": counts,
        "r3_verified": 55820, "r3_proven_ineligible": 1995, "r3_unknown": 54053,
        "new_verified": verified - 55820, "new_proven_ineligible": ineligible - 1995,
        "changed_keys": len(transitions),
        "transition_counts": [{"from": a, "to": b, "rows": int(n)}
                              for (a, b), n in sorted(transition_counts.items())],
        "remaining_unknown_dependency_counts_nonexclusive": {
            **{column: int(unknown_rows[column].eq(True).sum()) for column in DEPENDENCIES[:6]},
            **{column + "_false": int(unknown_rows[column].eq(False).sum())
               for column in DEPENDENCIES[6:]},
        },
        "model_objects_loaded_in_r4": 0, "prediction_calls_in_r4": 0,
        "model_fit_calls_in_r4": 0, "preprocessor_fit_calls_in_r4": 0,
        "formal_prediction_saved": False, "formal_accounting_replay_executed": False,
    }
    (OUT / "R4_GATE_SUMMARY.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(json.dumps({"verified": verified, "ineligible": ineligible, "unknown": unknown,
                      "changed": len(transitions)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
