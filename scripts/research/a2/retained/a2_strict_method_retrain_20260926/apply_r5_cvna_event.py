"""Apply the primary-source CVNA split proof to r4 candidate keys, read only models."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
STAGE = HERE / "test2026_stage"
R4 = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results\test2026\evidence_continuation_20260926_r4\r4_continuation")
OUT = STAGE / "r5_delta"
EVENT = STAGE / "r4_event_pit"
KEY = ["cusip", "title_of_class", "quarter", "signal_date"]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def key_digest(frame: pd.DataFrame) -> str:
    keys = frame[KEY].sort_values(KEY, kind="mergesort")
    return hashlib.sha256(pd.util.hash_pandas_object(keys, index=False).to_numpy().tobytes()).hexdigest()


def main() -> None:
    boundary = json.loads((OUT / "R5_IMMUTABLE_BOUNDARY.json").read_text("utf-8"))
    verdict = json.loads((EVENT / "CVNA_94_SHARE_EVENT_VERDICT.json").read_text("utf-8"))
    paths = {
        "r4_event_issuer_proxy_sha256": EVENT / "raw_share_events/CVNA_2026_proxy.pdf",
        "r4_event_exchange_alert_sha256": EVENT / "raw_share_events/CVNA_2026_05_07_MIAX.html",
        "r4_event_occ_original_sha256": EVENT / "raw_share_events/CVNA_OCC_58924.pdf",
    }
    for column, path in paths.items():
        assert path.exists(), path
        expected = {"r4_event_issuer_proxy_sha256": "issuer_proxy_sha256",
                    "r4_event_exchange_alert_sha256": "exchange_alert_sha256",
                    "r4_event_occ_original_sha256": "OCC_memo_sha256"}[column]
        assert sha(path) == verdict[expected]
    assert verdict["event_ex_date"] == "2026-05-08"
    assert verdict["OCC_memo_date"] < verdict["event_ex_date"]
    assert verdict["consumed_factor_a"] == 0.2 and verdict["consumed_factor_b"] == 0
    assert verdict["original_cusip_and_class"] == "146869102 CL A"
    assert verdict["all_other_r4_input_checks_true"]
    assert all(x["full_vs_prefix_32_features_exact"] for x in verdict["original_full_vs_prefix_32_features"])

    source = R4 / "R4_FINAL_CANDIDATE_INPUT_GATE.parquet"
    assert sha(source) == boundary["parent_r4_ledger_sha256"]
    prior = pd.read_parquet(source)
    assert len(prior) == boundary["candidate_days"] and key_digest(prior) == boundary["candidate_key_fingerprint_sha256"]
    proof = pd.read_parquet(EVENT / "CVNA_94_SHARE_EVENT_EXACT_KEY_PASS_OVERLAY.parquet")
    assert len(proof) == 94 and not proof.duplicated(KEY).any()
    proof = proof.rename(columns={column: "cvna_" + column for column in proof.columns if column not in KEY})
    after = prior.merge(proof, on=KEY, how="left", validate="one_to_one", indicator="_cvna_match")
    mask = after._cvna_match.eq("both")
    assert int(mask.sum()) == 94
    assert after.loc[mask, "final_input_gate"].eq("UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME").all()
    assert after.loc[mask, "2026_event_publication_time_unverified"].all()
    assert after.loc[mask, "cvna_r4_input_result_subject_to_parent_gate"].eq("INPUT_VERIFIED_THIS_GATE").all()
    assert after.loc[mask, "cvna_r4_event_public_ratio_proven"].all()
    assert after.loc[mask, "cusip"].eq("146869102").all()
    assert after.loc[mask, "title_of_class"].eq("CL A").all()
    assert after.loc[mask, "signal_date"].ge("2026-05-08").all()
    assert after.loc[mask, "feature_error"].fillna("").eq("").all()
    assert after.loc[mask, ["lookback_121_eligible", "has_32_finite", "version_checked"]].all().all()
    assert not after.loc[mask, ["proven_lifecycle_ineligible", "proven_121_ineligible",
                                "no_frozen_coordinate_overlap", "unexplained_raw_jump_dependency",
                                "multi_cusip_transport_interval_pending"]].any().any()
    for column in paths:
        assert after.loc[mask, "cvna_" + column].eq(sha(paths[column])).all()
    after["pre_cvna_event_gate"] = after.final_input_gate
    after.loc[mask, "2026_event_publication_time_unverified"] = False
    after.loc[mask, "final_input_gate"] = "INPUT_VERIFIED_THIS_GATE"
    after = after.drop(columns="_cvna_match")
    assert len(after) == 111868 and not after.duplicated(KEY).any()
    assert key_digest(after) == boundary["candidate_key_fingerprint_sha256"]
    original_columns = prior.columns.tolist()
    pd.testing.assert_frame_equal(after.loc[~mask, original_columns].reset_index(drop=True),
                                  prior.loc[~mask, original_columns].reset_index(drop=True),
                                  check_dtype=True)
    changed_original_columns = [column for column in original_columns if column not in
                                ("2026_event_publication_time_unverified", "final_input_gate")]
    pd.testing.assert_frame_equal(after.loc[mask, changed_original_columns].reset_index(drop=True),
                                  prior.loc[mask, changed_original_columns].reset_index(drop=True),
                                  check_dtype=True)
    OUT.mkdir(exist_ok=True)
    after.to_parquet(OUT / "R5_FINAL_CANDIDATE_INPUT_GATE.parquet", index=False)
    after.loc[mask, KEY + ["ticker", "moomoo_transport_code", "r3_final_input_gate",
                           "pre_cvna_event_gate", "final_input_gate", "cvna_r4_event_result",
                           "cvna_r4_event_occ_original_sha256"]].to_parquet(
        OUT / "R5_CVNA_94_STATUS_TRANSITIONS.parquet", index=False)
    counts = after.final_input_gate.value_counts().to_dict()
    report = {"status": "CVNA_PRIMARY_SPLIT_PROOF_APPLIED_EXACT_KEY",
              "r4_ledger_sha256": boundary["parent_r4_ledger_sha256"],
              "r5_ledger_sha256": sha(OUT / "R5_FINAL_CANDIDATE_INPUT_GATE.parquet"),
              "candidate_key_fingerprint_sha256": key_digest(after),
              "new_verified_candidate_days": 94,
              "verified": int(after.final_input_gate.str.startswith("INPUT_VERIFIED").sum()),
              "proven_ineligible": int(after.final_input_gate.str.startswith("PROVEN_").sum()),
              "remaining_unknown": int(after.final_input_gate.str.startswith("UNKNOWN_").sum()),
              "gate_counts": counts,
              "model_objects_loaded": 0, "model_fit_calls": 0, "preprocessor_fit_calls": 0}
    assert report["verified"] + report["proven_ineligible"] + report["remaining_unknown"] == 111868
    (OUT / "R5_CVNA_APPLICATION_REPORT.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    print(json.dumps({"verified": report["verified"], "unknown": report["remaining_unknown"]}))


if __name__ == "__main__":
    main()
