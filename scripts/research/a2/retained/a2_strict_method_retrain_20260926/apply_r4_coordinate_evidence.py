"""Apply independently proved original-coordinate equivalence by exact key."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
STAGE = HERE / "test2026_stage"
R3 = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results\test2026\identity_feature_application_20260926_r3")
COORD = STAGE / "r4_coordinate/COORDINATE_14841_EXACT_CANDIDATE_MAPPING.parquet"
OUT = STAGE / "r4_continuation"
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
    OUT.mkdir(exist_ok=True)
    baseline = json.loads((STAGE / "r4_validation/R3_BASELINE_EXACT_KEY_AND_HASH.json").read_text(encoding="utf-8"))
    base_path = R3 / "FINAL_111868_CANDIDATE_INPUT_GATE.parquet"
    assert sha(base_path) == baseline["r3_input_file_sha256"][base_path.name]
    base = pd.read_parquet(base_path)
    coordinate = pd.read_parquet(COORD)
    assert len(base) == 111868 and len(coordinate) == 14841
    assert not base.duplicated(KEY).any() and not coordinate.duplicated(KEY).any()
    assert key_hash(base) == baseline["candidate_key_fingerprint_sha256"]
    coordinate = coordinate[KEY + ["coordinate_evidence_class", "coordinate_gap_closure_proposed",
                                   "other_saved_close_exact", "other_saved_volume_exact"]]
    updated = base.merge(coordinate, on=KEY, how="left", validate="one_to_one", indicator=True)
    match = updated._merge.eq("both")
    assert int(match.sum()) == 14841
    assert updated.loc[match, "final_input_gate"].eq("UNKNOWN_FROZEN_COORDINATE_NO_OVERLAP").all()
    closure = updated.coordinate_gap_closure_proposed.fillna(False).to_numpy(dtype=bool)
    assert int(closure.sum()) == 4595
    assert updated.loc[closure, ["other_saved_close_exact", "other_saved_volume_exact"]].all().all()
    assert not updated.loc[closure, ["proven_lifecycle_ineligible", "proven_121_ineligible",
                                     "multi_cusip_transport_interval_pending"]].any().any()
    assert updated.loc[closure, "feature_error"].fillna("").eq("").all()
    assert updated.loc[closure, ["lookback_121_eligible", "has_32_finite"]].all().all()
    assert not updated.loc[closure, ["2026_event_publication_time_unverified",
                                     "unexplained_raw_jump_dependency"]].any().any()
    updated["r3_final_input_gate"] = updated.final_input_gate
    updated.loc[closure, "final_input_gate"] = "INPUT_VERIFIED_INDEPENDENT_ORIGINAL_COORDINATE"
    updated = updated.drop(columns=["_merge"])
    assert len(updated) == 111868 and key_hash(updated) == baseline["candidate_key_fingerprint_sha256"]
    target = OUT / "R4_COORDINATE_APPLIED_CANDIDATE_LEDGER.parquet"
    updated.to_parquet(target, index=False)
    transitions = updated.loc[updated.r3_final_input_gate.ne(updated.final_input_gate), KEY +
                              ["ticker", "moomoo_transport_code", "r3_final_input_gate", "final_input_gate",
                               "coordinate_evidence_class"]]
    assert len(transitions) == 4595
    transitions.to_parquet(OUT / "R4_COORDINATE_STATUS_TRANSITIONS.parquet", index=False)
    counts = updated.final_input_gate.value_counts().to_dict()
    report = {"status": "INDEPENDENT_ORIGINAL_COORDINATE_EVIDENCE_APPLIED_EXACT_KEY",
              "r3_sha256": sha(base_path), "coordinate_mapping_sha256": sha(COORD),
              "candidate_key_fingerprint_sha256": key_hash(updated),
              "closed_no_overlap_candidate_days": len(transitions),
              "remaining_unknown_candidate_days": int(updated.final_input_gate.str.startswith("UNKNOWN").sum()),
              "counts": counts, "model_objects_loaded": 0, "fit_calls": 0,
              "scope": "Only the no-event/no-jump independent-coordinate subset; event, Raw, identity and history gates unchanged."}
    (OUT / "R4_COORDINATE_APPLICATION_REPORT.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"closed": len(transitions), "remaining_unknown": report["remaining_unknown_candidate_days"]}))


if __name__ == "__main__":
    main()
