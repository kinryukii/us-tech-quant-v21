"""Load the date-complete revision without changing the frozen v1 loader."""
from __future__ import annotations

import json
from pathlib import Path

import joblib

import joint_linear_tree as original


class CoverageV2Policy(original.JointActionValuePolicy):
    def __init__(self, name, stage, artifacts_root):
        if stage not in ("validation", "final"):
            raise ValueError("UNKNOWN_STAGE")
        self.name, self.stage = name, stage
        root = Path(artifacts_root).resolve()
        receipt = json.loads((root / "FIT_RECEIPT.json").read_text(encoding="utf-8"))
        if receipt["status"] != "PASS" or receipt["revision"] != "DATE_COMPLETE_WITHIN_DAY_HASH_V2":
            raise RuntimeError("NOT_COMPLETED_V2_RECEIPT")
        names = ("q10", "q50", "q90") if name == "quantile_risk" else (name,)
        self.models = {}
        for model_name in names:
            if model_name not in original.NAMES:
                raise ValueError("UNKNOWN_MODEL")
            record = next(r for r in receipt["fits"] if r["stage"] == stage and r["name"] == model_name)
            # A numerical continuation is permitted only when explicitly recorded
            # as same-objective and used for this version's policy.
            repairs = [r for r in receipt.get("numerical_repairs", [])
                       if r["stage"] == stage and r["name"] == model_name and r["used_for_policy"]]
            if repairs:
                record = repairs[-1]
            artifact = root / Path(record["artifact"]).name
            if original.sha(artifact) != record["artifact_sha256"]:
                raise RuntimeError(f"V2_ARTIFACT_HASH_MISMATCH:{artifact.name}")
            self.models[model_name] = joblib.load(artifact)
        self.last_actions = None


def load_policy_v2(name, stage="final", artifacts_root=None):
    if artifacts_root is None:
        raise ValueError("artifacts_root must point to the explicit v2 output")
    return CoverageV2Policy(name, stage, artifacts_root)
