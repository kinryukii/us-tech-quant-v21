"""Score the one R2.4 frozen model in outcome-free research-shadow mode."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from fast3.models.two_stage_direction_hard_r24 import R4ContractError, write_json


def _probability(model, x, target):
    classes = list(model.classes_)
    return model.predict_proba(x)[:, classes.index(target)] if target in classes else np.zeros(len(x), dtype=float)


def main() -> int:
    parser = argparse.ArgumentParser(description="FAST3 R4 research-shadow scorer; no broker or order capability")
    parser.add_argument("--frozen-root", required=True)
    parser.add_argument("--input-parquet", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    frozen, output = Path(args.frozen_root), Path(args.output_root)
    try:
        output.absolute().relative_to(Path(__file__).resolve().parents[3].absolute())
    except ValueError:
        pass
    else:
        raise R4ContractError("REPOSITORY_OUTPUT_PATH_FORBIDDEN")
    model_path, manifest_path = frozen / "FAST3_R4_PROSPECTIVE_SHADOW_MODEL.joblib", frozen / "FAST3_R4_PROSPECTIVE_FREEZE.json"
    if not model_path.is_file() or not manifest_path.is_file():
        raise R4ContractError("PROSPECTIVE_MODEL_NOT_FROZEN")
    if json.loads(manifest_path.read_text(encoding="utf-8")).get("status") != "FROZEN_FOR_FUTURE_BLIND_RESEARCH_SHADOW_ONLY":
        raise R4ContractError("PROSPECTIVE_MODEL_FREEZE_STATUS_INVALID")
    raw = pd.read_parquet(args.input_parquet)
    outcomes = {"label", "future_label", "gross_return", "target_hit", "hit_timestamp_et", "horizon_timestamp_et"}
    if outcomes.intersection(raw.columns):
        raise R4ContractError("PROSPECTIVE_INPUT_CONTAINS_OUTCOME")
    if "decision_timestamp_et" not in raw or "feature_available_at_et" not in raw:
        raise R4ContractError("PROSPECTIVE_PIT_TIMESTAMP_MISSING")
    if (pd.to_datetime(raw.feature_available_at_et, utc=True) > pd.to_datetime(raw.decision_timestamp_et, utc=True)).any():
        raise R4ContractError("PROSPECTIVE_FEATURE_NOT_AVAILABLE_AT_DECISION")
    bundle = joblib.load(model_path); x = bundle["preprocessor"].transform(raw, bundle["features"])
    event = _probability(bundle["stage1"], x, 1)
    up, down = event * _probability(bundle["stage2"], x, "UP_FIRST"), event * _probability(bundle["stage2"], x, "DOWN_FIRST")
    output.mkdir(parents=True, exist_ok=True)
    scored = raw[["decision_timestamp_et"]].copy(); scored["p_up_first"] = up; scored["p_down_first"] = down
    scored["p_event"] = event; scored["combined_score"] = scored[["p_up_first", "p_down_first"]].max(axis=1)
    scored["shadow_direction"] = scored.apply(lambda row: "UP_FIRST" if row.p_up_first >= row.p_down_first else "DOWN_FIRST", axis=1)
    scored.to_parquet(output / "fast3_r4_prospective_shadow_scores.parquet", index=False)
    write_json(output / "fast3_r4_prospective_shadow_manifest.json", {"status": "RESEARCH_SHADOW_ONLY", "rows": len(scored),
               "outcome_columns_read": 0, "broker_action_performed": False, "paper_order_performed": False, "live_order_performed": False})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
