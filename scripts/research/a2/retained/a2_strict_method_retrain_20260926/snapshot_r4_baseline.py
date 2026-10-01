"""Freeze exact r3 inputs and candidate-key set before additive r4 evidence work."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
R3 = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results\test2026\identity_feature_application_20260926_r3")
OUT = HERE / "test2026_stage/r4_validation"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    OUT.mkdir(exist_ok=True)
    names = ["FINAL_111868_CANDIDATE_INPUT_GATE.parquet", "CONSUMED_REHAB_EVENT_AUDIT.parquet",
             "ORIGINAL_32_FEATURES_2026_CANDIDATE_INPUT_ONLY.parquet", "CONSUMED_2026_INITIAL_ADJUSTMENT_STATE.csv"]
    paths = {name: R3 / name for name in names}
    ledger = pd.read_parquet(paths[names[0]])
    key = ["cusip", "title_of_class", "quarter", "signal_date"]
    assert len(ledger) == 111868 and not ledger.duplicated(key).any()
    assert ledger.signal_date.nunique() == 181
    counts = ledger.final_input_gate.value_counts().to_dict()
    assert counts == {
        "INPUT_VERIFIED_THIS_GATE": 55820,
        "UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME": 35206,
        "UNKNOWN_FROZEN_COORDINATE_NO_OVERLAP": 14841,
        "UNKNOWN_RAW_REHAB_OR_ALIAS_IDENTITY": 2849,
        "PROVEN_LIFECYCLE_INELIGIBLE": 1707,
        "UNKNOWN_121_HISTORY": 768,
        "PROVEN_ORIGINAL_121_INELIGIBLE": 288,
        "UNKNOWN_UNEXPLAINED_RAW_JUMP": 208,
        "UNKNOWN_MULTI_CUSIP_TRANSPORT_INTERVAL": 181,
    }
    assert sum(counts.values()) == len(ledger)
    sorted_keys = ledger[key].sort_values(key, kind="mergesort")
    key_digest = hashlib.sha256(pd.util.hash_pandas_object(sorted_keys, index=False).to_numpy().tobytes()).hexdigest()
    result = {"status": "R3_EXACT_KEY_BASELINE_LOCKED_FOR_ADDITIVE_R4",
              "candidate_days": len(ledger), "signals": ledger.signal_date.nunique(),
              "candidate_key": key, "candidate_key_fingerprint_sha256": key_digest,
              "quarter_rows": ledger.quarter.value_counts().sort_index().to_dict(),
              "gate_counts": counts,
              "r3_input_file_sha256": {name: sha(path) for name, path in paths.items()},
              "fit_calls": 0, "model_objects_loaded": 0}
    (OUT / "R3_BASELINE_EXACT_KEY_AND_HASH.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(ledger), "signals": result["signals"], "key_hash": key_digest}))


if __name__ == "__main__":
    main()
