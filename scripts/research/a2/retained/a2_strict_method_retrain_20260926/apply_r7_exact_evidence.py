"""Append exact-key r7 cash and IPO-121 evidence to the frozen A2 2026 gate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
STAGE = HERE / "test2026_stage"
R6 = STAGE / "r6_contract_correction/R6_FULL_CANDIDATE_INPUT_GATE.parquet"
CASH = STAGE / "r7_cash_first_event_proposal/R7_811_EXACT_KEY_PASS_PROPOSAL.parquet"
IPO = STAGE / "r7_prewarm_ipo/R7_53_IPO_ORIGINAL_121_INELIGIBLE_EXACT_KEYS.parquet"
OUT = STAGE / "r7_applied"
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
    assert sha(R6) == "46b4af4c87c760817bd9244ec82886b258a844b1b14dac96f3acfd5e0764e830"
    before = pd.read_parquet(R6)
    cash = pd.read_parquet(CASH)
    ipo = pd.read_parquet(IPO)
    assert (len(before), len(cash), len(ipo)) == (111868, 811, 53)
    assert not before.duplicated(KEY).any() and not cash.duplicated(KEY).any() and not ipo.duplicated(KEY).any()
    assert key_sha(before) == "0f4167d679f1e38b94ffff6488088ad27a6fa6ea1dfd84aa63f8308ae17f96d1"
    assert cash.proposed_input_gate.eq("INPUT_VERIFIED_THIS_GATE").all()
    assert ipo.proposed_gate.eq("PROVEN_ORIGINAL_121_INELIGIBLE").all()
    assert cash.historical_vendor_actual_receipt_observed.eq(False).all()
    index = pd.MultiIndex.from_frame(before[KEY])
    cash_mask = index.isin(pd.MultiIndex.from_frame(cash[KEY]))
    ipo_mask = index.isin(pd.MultiIndex.from_frame(ipo[KEY]))
    assert int(cash_mask.sum()) == 811 and int(ipo_mask.sum()) == 53
    assert not (cash_mask & ipo_mask).any()
    assert before.loc[cash_mask, "final_input_gate"].eq("UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME").all()
    assert before.loc[cash_mask, "2026_event_publication_time_unverified"].all()
    assert before.loc[cash_mask, ["lookback_121_eligible", "has_32_finite", "version_checked"]].all().all()
    assert not before.loc[cash_mask, ["proven_lifecycle_ineligible", "proven_121_ineligible",
                                      "no_frozen_coordinate_overlap", "unexplained_raw_jump_dependency",
                                      "multi_cusip_transport_interval_pending"]].any().any()
    assert before.loc[ipo_mask, "final_input_gate"].eq("UNKNOWN_121_HISTORY").all()
    assert not before.loc[ipo_mask, "lookback_121_eligible"].fillna(False).any()
    assert ipo.available_public_sessions_inclusive.lt(121).all()

    after = before.copy()
    after.loc[cash_mask, "2026_event_publication_time_unverified"] = False
    after.loc[cash_mask, "final_input_gate"] = "INPUT_VERIFIED_THIS_GATE"
    after.loc[ipo_mask, "proven_121_ineligible"] = True
    after.loc[ipo_mask, "final_input_gate"] = "PROVEN_ORIGINAL_121_INELIGIBLE"
    untouched = ~(cash_mask | ipo_mask)
    pd.testing.assert_frame_equal(after.loc[untouched, before.columns].reset_index(drop=True),
                                  before.loc[untouched].reset_index(drop=True), check_dtype=True)
    assert key_sha(after) == key_sha(before)
    assert len(after) == 111868 and not after.duplicated(KEY).any()
    verified = after.final_input_gate.str.startswith("INPUT_VERIFIED")
    ineligible = after.final_input_gate.str.startswith("PROVEN_")
    unknown = after.final_input_gate.str.startswith("UNKNOWN_")
    assert (int(verified.sum()), int(ineligible.sum()), int(unknown.sum())) == (62774, 2257, 46837)
    OUT.mkdir(parents=True, exist_ok=True)
    final = OUT / "R7_FINAL_CANDIDATE_INPUT_GATE.parquet"
    after.to_parquet(final, index=False)
    transition_cols = KEY + ["ticker", "moomoo_transport_code", "final_input_gate"]
    after.loc[cash_mask, transition_cols].to_parquet(OUT / "R7_811_CASH_STATUS_TRANSITIONS.parquet", index=False)
    after.loc[ipo_mask, transition_cols].to_parquet(OUT / "R7_53_IPO_121_STATUS_TRANSITIONS.parquet", index=False)
    gap_cols = KEY + ["ticker", "moomoo_transport_code", "final_input_gate", "feature_error",
                      "first_consumed_2026_event", "first_unexplained_2026_jump", "coordinate_evidence_class",
                      "2026_event_publication_time_unverified", "no_frozen_coordinate_overlap",
                      "unexplained_raw_jump_dependency", "multi_cusip_transport_interval_pending",
                      "lookback_121_eligible", "has_32_finite", "version_checked"]
    after.loc[unknown, gap_cols].to_parquet(OUT / "R7_REMAINING_CANDIDATE_GAPS.parquet", index=False)
    after.groupby(["quarter", "final_input_gate"]).size().rename("candidate_days").reset_index().to_csv(
        OUT / "R7_QUARTER_GATE_SUMMARY.csv", index=False)
    daily = after.groupby(["signal_date", "final_input_gate"]).size().rename("candidate_days").reset_index()
    daily.to_csv(OUT / "R7_SIGNAL_DATE_GATE_SUMMARY.csv", index=False)
    daily_unknown = after.loc[unknown].groupby("signal_date").size()
    assert len(daily_unknown) == after.signal_date.nunique() == 181
    summary = {"status": "COMMON_CANDIDATE_GATE_INCOMPLETE_AFTER_R7_EXACT_EVIDENCE",
               "candidate_days": len(after), "signal_days": after.signal_date.nunique(),
               "candidate_key_fingerprint_sha256": key_sha(after),
               "parent_r6_sha256": sha(R6), "r7_final_sha256": sha(final),
               "cash_proposal_sha256": sha(CASH), "ipo_121_proposal_sha256": sha(IPO),
               "new_verified_cash_exact_keys": int(cash_mask.sum()),
               "new_proven_121_ineligible_exact_keys": int(ipo_mask.sum()),
               "verified": int(verified.sum()), "proven_ineligible": int(ineligible.sum()),
               "remaining_unknown": int(unknown.sum()),
               "signal_days_with_complete_candidate_gate": 0,
               "minimum_unknown_on_any_signal_day": int(daily_unknown.min()),
               "main_status_counts": after.final_input_gate.value_counts().to_dict(),
               "test_asof_utc": "2026-09-25T18:10:21.6494935Z",
               "last_signal": "2026-09-22", "last_execution": "2026-09-23",
               "terminal_valuation": "2026-09-24", "four_frozen_model_objects_loaded": 0,
               "four_frozen_model_fit_calls": 0, "preprocessor_fit_calls_in_test2026": 0,
               "formal_predictions": 0, "formal_accounting_replays": 0}
    (OUT / "R7_GATE_SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", "utf-8")
    print(json.dumps({"verified": summary["verified"], "ineligible": summary["proven_ineligible"],
                      "unknown": summary["remaining_unknown"], "complete_signal_days": 0}))


if __name__ == "__main__":
    main()
