"""Apply the independent FLYX same-class market-price corroboration by key."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
STAGE = HERE / "test2026_stage"
OUT = STAGE / "r4_continuation"
IDENT = STAGE / "r4_identity"
KEY = ["cusip", "title_of_class", "quarter", "signal_date"]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def key_hash(data: pd.DataFrame) -> str:
    ordered = data[KEY].sort_values(KEY, kind="mergesort")
    return hashlib.sha256(pd.util.hash_pandas_object(ordered, index=False).to_numpy().tobytes()).hexdigest()


def main() -> None:
    baseline = json.loads((STAGE / "r4_validation/R3_BASELINE_EXACT_KEY_AND_HASH.json").read_text(encoding="utf-8"))
    prior = pd.read_parquet(OUT / "R4_COORDINATE_IDENTITY_APPLIED_CANDIDATE_LEDGER.parquet")
    proof = pd.read_parquet(IDENT / "FLYX_177_EXACT_KEY_PASS_OVERLAY.parquet")
    assert len(proof) == 177 and not proof.duplicated(KEY).any()
    prospectus = IDENT / "FLYX_ISSUER_PROSPECTUS_20260109.html"
    assert sha(prospectus) == "5fb0dcd3c6f547e3fe6f629670ac9efd8171ebf7896c6ece26919ba25e45ede9"
    updated = prior.merge(proof[KEY + ["r4_dependency_result", "official_price_source"]],
                          on=KEY, how="left", validate="one_to_one", indicator=True)
    mask = updated._merge.eq("both")
    assert int(mask.sum()) == 177
    assert updated.loc[mask, "final_input_gate"].eq("UNKNOWN_UNEXPLAINED_RAW_JUMP").all()
    assert updated.loc[mask, "r4_dependency_result"].eq(
        "JUMP_IS_CORROBORATED_UNADJUSTED_SAME_CLASS_MARKET_MOVE").all()
    assert updated.loc[mask, "feature_error"].fillna("").eq("").all()
    assert updated.loc[mask, ["lookback_121_eligible", "has_32_finite", "version_checked"]].all().all()
    assert not updated.loc[mask, ["proven_lifecycle_ineligible", "proven_121_ineligible",
                                  "multi_cusip_transport_interval_pending",
                                  "2026_event_publication_time_unverified"]].any().any()
    updated["pre_jump_gate"] = updated.final_input_gate
    updated.loc[mask, "unexplained_raw_jump_dependency"] = False
    updated.loc[mask, "final_input_gate"] = "INPUT_VERIFIED_THIS_GATE"
    updated = updated.drop(columns=["_merge"])
    assert len(updated) == 111868 and key_hash(updated) == baseline["candidate_key_fingerprint_sha256"]
    updated.to_parquet(OUT / "R4_COORDINATE_IDENTITY_JUMP_APPLIED_CANDIDATE_LEDGER.parquet", index=False)
    updated.loc[mask, KEY + ["ticker", "moomoo_transport_code", "r3_final_input_gate",
                             "pre_jump_gate", "final_input_gate", "r4_dependency_result"]].to_parquet(
        OUT / "R4_FLYX_177_STATUS_TRANSITIONS.parquet", index=False)
    report = {"status": "FLYX_GENUINE_SAME_CLASS_RAW_JUMP_EVIDENCE_APPLIED_EXACT_KEY",
              "new_verified_candidate_days": 177,
              "unknown_candidate_days": int(updated.final_input_gate.str.startswith("UNKNOWN").sum()),
              "remaining_sion_jump_unknown_days": int((updated.moomoo_transport_code.eq("US.SION")
                  & updated.final_input_gate.eq("UNKNOWN_UNEXPLAINED_RAW_JUMP")).sum()),
              "prospectus_original_body_sha256": sha(prospectus),
              "candidate_key_fingerprint_sha256": key_hash(updated),
              "model_objects_loaded": 0, "fit_calls": 0}
    (OUT / "R4_FLYX_APPLICATION_REPORT.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"new_verified": 177, "unknown": report["unknown_candidate_days"]}))


if __name__ == "__main__":
    main()
