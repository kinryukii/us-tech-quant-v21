"""Apply ten publicly reconstructible cash events under the original A2 gate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
STAGE = HERE / "test2026_stage"
EVENT = STAGE / "r4_event_pit"
OUT = STAGE / "r6_contract_correction"
R5 = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results\test2026\evidence_continuation_20260927_r5")
KEY = ["cusip", "title_of_class", "quarter", "signal_date"]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def key_sha(frame: pd.DataFrame) -> str:
    ordered = frame[KEY].sort_values(KEY, kind="mergesort")
    return hashlib.sha256(pd.util.hash_pandas_object(ordered, index=False).to_numpy().tobytes()).hexdigest()


def main() -> None:
    OUT.mkdir(exist_ok=True)
    parent = R5 / "R5_FINAL_CANDIDATE_INPUT_GATE.parquet"
    assert sha(parent) == "1e14e19edf5ca01a097f1b2b2955e45e3b0e5831782d49ea6e5508053985e42a"
    rule = STAGE / "finra_rule_11140_2026_snapshot.html"
    assert sha(rule) == "97fd2bd3311735aa6be301d9b5f677dfd5826b91b8797ed3d8220129e9910e1f"
    rule_text = rule.read_text("utf-8", errors="ignore")
    assert "less than 25 percent" in rule_text and "record date if the record date falls on a business day" in rule_text
    assert "Amended by SR-FINRA-2023-017 eff. May 28, 2024" in rule_text
    verdicts = pd.read_csv(EVENT / "TEN_CASH_EVENTS_ORIGINAL_CONTRACT_VERDICTS.csv", keep_default_na=False)
    assert len(verdicts) == 10 and verdicts.event_code.nunique() == 10
    assert (verdicts.cash_to_prior_raw_close_pct.astype(float) < 25).all()
    assert (verdicts.cash_to_prior_raw_close_pct.astype(float) > 0).all()
    assert (verdicts.consumed_factor_a.astype(float) == verdicts.reproduced_floor5_factor_a.astype(float)).all()
    assert (verdicts.record_date == verdicts.original_vendor_exdate).all()
    assert (verdicts.public_date < verdicts.record_date).all()
    assert verdicts.exdate_basis.isin({
        "CONTEMPORANEOUS_ISSUER_EXDATE",
        "RETROSPECTIVE_ISSUER_HISTORY_EXDATE_PLUS_FINRA_11140_B1",
        "FINRA_11140_B1_NORMAL_RECORD_EQUALS_EXDATE_CORROBORATED_BY_ORIGINAL_VENDOR_EXDATE",
    }).all()
    assert verdicts.all_other_r4_gates_pass.astype(str).str.lower().eq("true").all()
    proof = pd.read_parquet(EVENT / "TEN_CASH_EVENTS_585_EXACT_KEY_PASS_PROPOSAL.parquet")
    assert len(proof) == int(verdicts.exact_candidate_keys.sum()) == 585
    assert not proof.duplicated(KEY).any()
    assert set(proof.event_code) == set(verdicts.event_code)
    proof = proof.merge(verdicts[["event_code", "record_date", "next_unproved_event_exclusive",
                                  "consumed_factor_a", "public_date"]].rename(
        columns={"record_date": "verified_record_date", "next_unproved_event_exclusive": "verified_next_event",
                 "consumed_factor_a": "verified_factor_a", "public_date": "verified_public_date"}),
        on="event_code", how="left", validate="many_to_one")
    assert proof.record_date.eq(proof.verified_record_date).all()
    assert proof.next_unproved_event_exclusive.eq(proof.verified_next_event).all()
    assert proof.consumed_factor_a.astype(float).eq(proof.verified_factor_a.astype(float)).all()
    assert proof.source_public_date.eq(proof.verified_public_date).all()
    signal_day = pd.to_datetime(proof.signal_date).dt.normalize()
    event_day = pd.to_datetime(proof.event_date).dt.normalize()
    next_event_day = pd.to_datetime(proof.next_unproved_event_exclusive).dt.normalize()
    public_day = pd.to_datetime(proof.source_public_date).dt.normalize()
    assert signal_day.ge(event_day).all()
    assert signal_day.lt(next_event_day).all()
    assert public_day.lt(signal_day).all()
    assert proof.proposed_input_gate.eq("INPUT_VERIFIED_THIS_GATE").all()

    before = pd.read_parquet(parent)
    assert len(before) == 111868 and key_sha(before) == "0f4167d679f1e38b94ffff6488088ad27a6fa6ea1dfd84aa63f8308ae17f96d1"
    proof = proof.rename(columns={c: "cash_proof_" + c for c in proof if c not in KEY})
    after = before.merge(proof, on=KEY, how="left", validate="one_to_one", indicator="_cash_match")
    mask = after._cash_match.eq("both")
    assert int(mask.sum()) == 585
    assert after.loc[mask, "final_input_gate"].eq("UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME").all()
    assert after.loc[mask, "2026_event_publication_time_unverified"].all()
    assert after.loc[mask, "feature_error"].fillna("").eq("").all()
    assert after.loc[mask, ["lookback_121_eligible", "has_32_finite", "version_checked"]].all().all()
    assert not after.loc[mask, ["proven_lifecycle_ineligible", "proven_121_ineligible",
                                "no_frozen_coordinate_overlap", "unexplained_raw_jump_dependency",
                                "multi_cusip_transport_interval_pending"]].any().any()
    assert after.loc[mask, "cash_proof_historical_vendor_receipt_proven"].eq(False).all()
    after["pre_cash_contract_gate"] = after.final_input_gate
    after.loc[mask, "2026_event_publication_time_unverified"] = False
    after.loc[mask, "final_input_gate"] = "INPUT_VERIFIED_THIS_GATE"
    after = after.drop(columns="_cash_match")
    original_columns = before.columns.tolist()
    pd.testing.assert_frame_equal(after.loc[~mask, original_columns].reset_index(drop=True),
                                  before.loc[~mask, original_columns].reset_index(drop=True), check_dtype=True)
    unaffected_columns = [c for c in original_columns if c not in
                          ("2026_event_publication_time_unverified", "final_input_gate")]
    pd.testing.assert_frame_equal(after.loc[mask, unaffected_columns].reset_index(drop=True),
                                  before.loc[mask, unaffected_columns].reset_index(drop=True), check_dtype=True)
    assert len(after) == 111868 and not after.duplicated(KEY).any()
    assert key_sha(after) == "0f4167d679f1e38b94ffff6488088ad27a6fa6ea1dfd84aa63f8308ae17f96d1"
    after.to_parquet(OUT / "R6_FINAL_CANDIDATE_INPUT_GATE.parquet", index=False)
    after.loc[mask, KEY + ["ticker", "moomoo_transport_code", "pre_cash_contract_gate", "final_input_gate",
                           "cash_proof_event_code", "cash_proof_exdate_basis", "cash_proof_source_tier",
                           "cash_proof_source_url", "cash_proof_source_body_sha256"]].to_parquet(
        OUT / "R6_TEN_CASH_EVENTS_585_STATUS_TRANSITIONS.parquet", index=False)
    verified = int(after.final_input_gate.str.startswith("INPUT_VERIFIED").sum())
    ineligible = int(after.final_input_gate.str.startswith("PROVEN_").sum())
    unknown = int(after.final_input_gate.str.startswith("UNKNOWN_").sum())
    assert (verified, ineligible, unknown) == (61452, 2204, 48212)
    report = {"status": "ORIGINAL_CONTRACT_CASH_EXDATE_EVIDENCE_APPLIED_EXACT_KEY",
              "parent_r5_ledger_sha256": sha(parent),
              "r6_ledger_sha256": sha(OUT / "R6_FINAL_CANDIDATE_INPUT_GATE.parquet"),
              "finra_rule_original_sha256": sha(rule),
              "candidate_days": len(after), "candidate_key_fingerprint_sha256": key_sha(after),
              "new_verified_candidate_days": int(mask.sum()),
              "verified": verified, "proven_ineligible": ineligible, "remaining_unknown": unknown,
              "gate_counts": after.final_input_gate.value_counts().to_dict(),
              "model_objects_loaded": 0, "model_fit_calls": 0, "preprocessor_fit_calls": 0,
              "historical_vendor_actual_receipt_claimed": False}
    (OUT / "R6_CASH_APPLICATION_REPORT.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    print(json.dumps({"new_verified": int(mask.sum()), "unknown": unknown}))


if __name__ == "__main__":
    main()
