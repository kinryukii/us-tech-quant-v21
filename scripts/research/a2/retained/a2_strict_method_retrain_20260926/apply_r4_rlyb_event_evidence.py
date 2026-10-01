"""Apply the dated RLYB split proof to the exact original candidate keys."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent / "test2026_stage"
OUT = ROOT / "r4_continuation"
EVENT = ROOT / "r4_event_pit"
KEY = ["cusip", "title_of_class", "quarter", "signal_date"]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def key_digest(frame: pd.DataFrame) -> str:
    keys = frame[KEY].sort_values(KEY, kind="mergesort")
    return hashlib.sha256(pd.util.hash_pandas_object(keys, index=False).to_numpy().tobytes()).hexdigest()


def main() -> None:
    baseline = json.loads((ROOT / "r4_validation/R3_BASELINE_EXACT_KEY_AND_HASH.json").read_text("utf-8"))
    verdict = json.loads((EVENT / "RLYB_EVENT_VERDICT.json").read_text("utf-8"))
    source = ROOT / "r4_identity/RLYB_NASDAQ_ECA2026_71.html"
    assert source.exists(), source
    assert digest(source).lower() == verdict["notice_original_body_sha256"].lower()
    assert verdict["notice_date"] < verdict["event_applied_date"]
    assert verdict["event_factor_a"] == 8 and verdict["event_factor_b"] == 0
    assert verdict["event_share_volume_scale_factor"] == 8
    assert verdict["all_181_other_r3_input_checks_true"]
    assert all(x["full_vs_prefix_exact"] and x["original_feature_columns"] == 32
               for x in verdict["original_feature_prefix_checks"])

    before = pd.read_parquet(OUT / "R4_COORDINATE_IDENTITY_JUMP_APPLIED_CANDIDATE_LEDGER.parquet")
    overlay = pd.read_parquet(EVENT / "RLYB_181_IDENTITY_EVENT_COMBINED_OVERLAY.parquet")
    assert len(before) == 111868 and key_digest(before) == baseline["candidate_key_fingerprint_sha256"]
    assert len(overlay) == 181 and not overlay.duplicated(KEY).any()
    after = before.merge(overlay[KEY + ["r4_event_public_ratio_proven", "r4_event_source_sha256",
                                        "r4_event_result", "r4_input_result_subject_to_parent_gate"]],
                         on=KEY, how="left", validate="one_to_one", indicator="_event_match")
    matched = after._event_match.eq("both")
    assert int(matched.sum()) == 181
    assert after.loc[matched, "r4_event_source_sha256"].str.lower().eq(digest(source).lower()).all()
    affected = matched & after.r4_event_public_ratio_proven.eq(True)
    unaffected = matched & ~affected
    assert int(affected.sum()) == 157 and int(unaffected.sum()) == 24
    assert after.loc[affected, "signal_date"].ge(verdict["event_applied_date"]).all()
    assert after.loc[unaffected, "signal_date"].lt(verdict["event_applied_date"]).all()
    assert after.loc[affected, "final_input_gate"].eq("UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME").all()
    assert after.loc[unaffected, "final_input_gate"].eq("INPUT_VERIFIED_THIS_GATE").all()
    assert after.loc[matched, "r4_input_result_subject_to_parent_gate"].eq("INPUT_VERIFIED_THIS_GATE").all()
    assert after.loc[matched, "feature_error"].fillna("").eq("").all()
    assert after.loc[matched, ["lookback_121_eligible", "has_32_finite", "version_checked"]].all().all()
    assert not after.loc[matched, ["proven_lifecycle_ineligible", "proven_121_ineligible",
                                   "multi_cusip_transport_interval_pending", "unexplained_raw_jump_dependency",
                                   "no_frozen_coordinate_overlap"]].any().any()
    after["pre_rlyb_event_gate"] = after.final_input_gate
    after.loc[affected, "2026_event_publication_time_unverified"] = False
    after.loc[affected, "final_input_gate"] = "INPUT_VERIFIED_THIS_GATE"
    after = after.drop(columns="_event_match")
    assert len(after) == 111868 and not after.duplicated(KEY).any()
    assert key_digest(after) == baseline["candidate_key_fingerprint_sha256"]
    after.to_parquet(OUT / "R4_FINAL_CANDIDATE_INPUT_GATE.parquet", index=False)
    after.loc[affected, KEY + ["ticker", "r3_final_input_gate", "pre_rlyb_event_gate", "final_input_gate",
                               "r4_event_source_sha256", "r4_event_result"]].to_parquet(
        OUT / "R4_RLYB_157_EVENT_STATUS_TRANSITIONS.parquet", index=False)
    report = {
        "status": "RLYB_SPLIT_PUBLIC_RATIO_EXACT_KEY_APPLIED",
        "candidate_days": len(after), "candidate_key_fingerprint_sha256": key_digest(after),
        "rlyb_event_affected_new_verified": int(affected.sum()),
        "rlyb_pre_event_kept_verified": int(unaffected.sum()),
        "remaining_unknown": int(after.final_input_gate.str.startswith("UNKNOWN").sum()),
        "counts": after.final_input_gate.value_counts().to_dict(),
        "historical_vendor_receipt_timestamp": "UNOBSERVED; original contract has no independent receipt gate",
        "model_objects_loaded": 0, "model_fit_calls": 0, "preprocessor_fit_calls": 0,
    }
    (OUT / "R4_RLYB_APPLICATION_REPORT.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    print(json.dumps({"new_verified": int(affected.sum()), "unknown": report["remaining_unknown"]}))


if __name__ == "__main__":
    main()
