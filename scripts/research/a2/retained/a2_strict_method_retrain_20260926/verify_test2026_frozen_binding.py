"""Inspect the exact saved model identities and callable execution source, read only."""
from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "test2026_stage/identity_feature_application_r1"
BASE = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results")
SOURCE = Path(r"D:\us-tech-quant\scripts\v22\fast_a2_r0f_corporate_action_and_nav_forensic_audit.py")
METHODS = ("hgb", "ridge", "elastic_net", "mlp")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    spec = importlib.util.spec_from_file_location("a2_actual_reconstruct_path_source", SOURCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    actual_path = Path(inspect.getsourcefile(module.reconstruct_path)).resolve()
    assert actual_path == SOURCE.resolve()
    evaluate = (HERE / "evaluate.py").read_text(encoding="utf-8")
    assert 'r0f = import_file("original_r0f_for_execution", R0F)' in evaluate
    assert "r0f.reconstruct_path(model=method" in evaluate
    common = BASE / "common_frozen.json"
    assert sha(common) == "ac5c4e82791bda9670c3f81660f2cdf7ae3cd191f7b333f894452eabaadb4f8e"
    freeze = json.loads((BASE / "pre2026_model_freeze.json").read_text(encoding="utf-8"))
    hashes = {}
    for method in METHODS:
        path = BASE / method / "final_full_pre2026.joblib"
        digest = sha(path)
        expected = next(x["sha256"] for x in freeze["models"][method]["fits"] if x["stage"] == "FULL_PRE2026")
        assert digest == expected
        hashes[method] = digest
    record = {"status": "READ_ONLY_BINDING_VERIFIED_FORMAL_REPLAY_NOT_STARTED",
              "actual_reconstruct_path_source": str(actual_path),
              "actual_reconstruct_path_source_sha256": sha(actual_path),
              "evaluate_call_site_sha256": sha(HERE / "evaluate.py"),
              "common_frozen_sha256": sha(common),
              "pre2026_model_freeze_sha256": sha(BASE / "pre2026_model_freeze.json"),
              "full_pre2026_model_sha256": hashes,
              "model_objects_loaded": 0, "new_model_fit_calls": 0, "new_preprocessor_fit_calls": 0}
    (OUT / "FROZEN_AND_ACCOUNTING_CALLABLE_BINDING.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(record["status"])


if __name__ == "__main__":
    main()
