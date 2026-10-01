"""Apply official first-trade and effective-dated CUSIP evidence by exact key."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
STAGE = HERE / "test2026_stage"
OUT = STAGE / "r4_continuation"
IDENT = STAGE / "r4_identity"
KEY = ["cusip", "title_of_class", "quarter", "signal_date"]


def key_hash(data: pd.DataFrame) -> str:
    ordered = data[KEY].sort_values(KEY, kind="mergesort")
    return hashlib.sha256(pd.util.hash_pandas_object(ordered, index=False).to_numpy().tobytes()).hexdigest()


def main() -> None:
    baseline = json.loads((STAGE / "r4_validation/R3_BASELINE_EXACT_KEY_AND_HASH.json").read_text(encoding="utf-8"))
    before = pd.read_parquet(OUT / "R4_COORDINATE_APPLIED_CANDIDATE_LEDGER.parquet")
    assert len(before) == 111868 and key_hash(before) == baseline["candidate_key_fingerprint_sha256"]
    prewarm = pd.read_parquet(IDENT / "PREWARM_209_EXACT_KEYS.parquet")
    rlyb = pd.read_parquet(IDENT / "RLYB_181_EXACT_KEY_INTERVAL_OVERLAY.parquet")
    assert len(prewarm) == 209 and len(rlyb) == 181
    assert not prewarm.duplicated(KEY).any() and not rlyb.duplicated(KEY).any()
    prewarm_cols = KEY + ["first_trade_official", "first_eligible_qqq_session",
                          "official_source_url", "official_local_original"]
    rlyb_cols = KEY + ["effective_cusip_on_signal", "original_13f_cusip_continues_via_split",
                       "r4_identity_result", "r4_identity_source"]
    updated = before.merge(prewarm[prewarm_cols], on=KEY, how="left", validate="one_to_one", indicator="_prewarm_match")
    updated = updated.merge(rlyb[rlyb_cols], on=KEY, how="left", validate="one_to_one", indicator="_rlyb_match")
    warm_mask = updated._prewarm_match.eq("both")
    rlyb_mask = updated._rlyb_match.eq("both")
    assert int(warm_mask.sum()) == 209 and int(rlyb_mask.sum()) == 181 and not (warm_mask & rlyb_mask).any()
    assert updated.loc[warm_mask, "final_input_gate"].eq("UNKNOWN_121_HISTORY").all()
    assert (updated.loc[warm_mask, "signal_date"] < pd.to_datetime(updated.loc[warm_mask, "first_eligible_qqq_session"])).all()
    assert updated.loc[rlyb_mask, "final_input_gate"].eq("UNKNOWN_MULTI_CUSIP_TRANSPORT_INTERVAL").all()
    assert updated.loc[rlyb_mask, "r4_identity_result"].eq(
        "SAME_COMMON_SHARE_ECONOMIC_SECURITY_EFFECTIVE_DATED_CUSIP_CHANGE").all()
    successor_mask = rlyb_mask & updated.cusip.eq("75120L100") & updated.effective_cusip_on_signal.eq("75120L209")
    assert int(successor_mask.sum()) == 73 and updated.loc[successor_mask, "original_13f_cusip_continues_via_split"].all()
    updated["pre_identity_gate"] = updated.final_input_gate
    updated.loc[warm_mask, "proven_121_ineligible"] = True
    updated.loc[warm_mask, "final_input_gate"] = "PROVEN_ORIGINAL_121_INELIGIBLE"
    updated.loc[rlyb_mask, "multi_cusip_transport_interval_pending"] = False
    subset = updated.loc[rlyb_mask]
    assert subset.feature_error.fillna("").eq("").all()
    assert subset[["lookback_121_eligible", "has_32_finite", "version_checked"]].all().all()
    assert not subset[["proven_lifecycle_ineligible", "proven_121_ineligible",
                       "unexplained_raw_jump_dependency"]].any().any()
    updated.loc[rlyb_mask, "final_input_gate"] = np.where(
        updated.loc[rlyb_mask, "2026_event_publication_time_unverified"],
        "UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME", "INPUT_VERIFIED_THIS_GATE")
    assert int((rlyb_mask & updated.final_input_gate.eq("INPUT_VERIFIED_THIS_GATE")).sum()) == 24
    assert int((rlyb_mask & updated.final_input_gate.eq("UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME")).sum()) == 157
    updated = updated.drop(columns=["_prewarm_match", "_rlyb_match"])
    assert len(updated) == 111868 and key_hash(updated) == baseline["candidate_key_fingerprint_sha256"]
    updated.to_parquet(OUT / "R4_COORDINATE_IDENTITY_APPLIED_CANDIDATE_LEDGER.parquet", index=False)
    transitions = updated.loc[updated.r3_final_input_gate.ne(updated.final_input_gate), KEY +
                              ["ticker", "moomoo_transport_code", "r3_final_input_gate", "final_input_gate",
                               "coordinate_evidence_class", "first_trade_official", "first_eligible_qqq_session",
                               "effective_cusip_on_signal", "r4_identity_source"]]
    assert len(transitions) == 4595 + 209 + 181
    transitions.to_parquet(OUT / "R4_COORDINATE_IDENTITY_STATUS_TRANSITIONS.parquet", index=False)
    counts = updated.final_input_gate.value_counts().to_dict()
    report = {"status": "COORDINATE_AND_IDENTITY_EVIDENCE_APPLIED_EXACT_KEY",
              "candidate_rows": len(updated), "key_hash": key_hash(updated),
              "coordinate_new_verified": 4595, "first_trade_new_proven_ineligible": 209,
              "rlyb_uid_interval_resolved": 181, "rlyb_input_verified_before_split": 24,
              "rlyb_after_split_event_version_still_unknown": 157,
              "counts": counts,
              "remaining_unknown": int(updated.final_input_gate.str.startswith("UNKNOWN").sum()),
              "model_objects_loaded": 0, "fit_calls": 0}
    (OUT / "R4_COORDINATE_IDENTITY_APPLICATION_REPORT.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"new_verified": 4619, "new_ineligible": 209, "unknown": report["remaining_unknown"]}))


if __name__ == "__main__":
    main()
