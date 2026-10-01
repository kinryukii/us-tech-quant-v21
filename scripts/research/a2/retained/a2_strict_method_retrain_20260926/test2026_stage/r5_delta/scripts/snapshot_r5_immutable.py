"""Record the r4-to-r5 immutable boundary using only projected candidate keys."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
PARENT = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results")
R4 = PARENT / "test2026/evidence_continuation_20260926_r4/r4_continuation"
OUT = HERE / "test2026_stage/r5_delta"
KEY = ["cusip", "title_of_class", "quarter", "signal_date"]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    OUT.mkdir(exist_ok=True)
    ledger = R4 / "R4_FINAL_CANDIDATE_INPUT_GATE.parquet"
    binding = PARENT / "test2026/identity_feature_application_20260926_r3/FROZEN_AND_ACCOUNTING_CALLABLE_BINDING.json"
    contract = PARENT / "test2026/test2026_contract.json"
    frozen = PARENT / "common_frozen.json"
    model_freeze = PARENT / "pre2026_model_freeze.json"
    keys = pd.read_parquet(ledger, columns=KEY)
    assert len(keys) == 111868 and keys.signal_date.nunique() == 181
    assert not keys.duplicated(KEY).any()
    fingerprint = hashlib.sha256(pd.util.hash_pandas_object(
        keys.sort_values(KEY, kind="mergesort"), index=False).to_numpy().tobytes()).hexdigest()
    assert fingerprint == "0f4167d679f1e38b94ffff6488088ad27a6fa6ea1dfd84aa63f8308ae17f96d1"
    old = json.loads((R4 / "R4_GATE_SUMMARY.json").read_text("utf-8"))
    assert sha(ledger) == old["r4_ledger_sha256"]
    record = {
        "purpose": "R5_ADDITIVE_EVIDENCE_ONLY_NO_MODEL_SCORE_PRIORITY",
        "parent_r4_ledger_sha256": sha(ledger),
        "candidate_key_fingerprint_sha256": fingerprint,
        "candidate_days": len(keys), "signal_days": keys.signal_date.nunique(),
        "test_asof_utc": old["test_asof_utc"],
        "last_signal": old["last_signal"], "last_execution": old["last_execution"],
        "terminal_valuation": old["terminal_valuation"],
        "frozen_and_execution_sha256": {
            "common_frozen": sha(frozen), "pre2026_model_freeze": sha(model_freeze),
            "test2026_contract": sha(contract), "r3_callable_binding": sha(binding),
        },
        "io_policy": "Project keys/needed columns; small per-code or per-event chunks; reuse r3 feature checkpoint; append only distinct proof and delta; no broad Raw download or full feature rebuild",
        "model_objects_loaded": 0, "model_fit_calls": 0, "preprocessor_fit_calls": 0,
    }
    (OUT / "R5_IMMUTABLE_BOUNDARY.json").write_text(json.dumps(record, indent=2) + "\n", "utf-8")
    print(json.dumps({"rows": len(keys), "r4_sha256": record["parent_r4_ledger_sha256"]}))


if __name__ == "__main__":
    main()
