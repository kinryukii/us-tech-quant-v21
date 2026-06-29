#!/usr/bin/env python
from pathlib import Path
import importlib.util

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/v21/v21_092_r4_micro_weight_shadow_stress_test_and_forward_plan_review.py"
SPEC = importlib.util.spec_from_file_location("v21_092_r4", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def t(value) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES"}


def f(value) -> bool:
    return str(value).strip().upper() in {"FALSE", "0", "NO"}


if __name__ == "__main__":
    out = ROOT / MODULE.OUT_REL
    result = MODULE.run_stage(ROOT) if not (out / MODULE.VALIDATION_NAME).is_file() else pd.read_csv(out / MODULE.VALIDATION_NAME).iloc[0].to_dict()
    assert out.is_dir()
    for name in MODULE.OUTPUT_NAMES:
        assert (out / name).is_file(), name
    val = pd.read_csv(out / MODULE.VALIDATION_NAME)
    assert len(val) == 1
    row = val.iloc[0]
    assert row["final_status"] in {
        "PASS_V21_092_R4_MICRO_SHADOW_FORWARD_PLAN_READY",
        "PARTIAL_PASS_V21_092_R4_MICRO_WEIGHT_STRESS_TEST_READY_NO_CANDIDATE_SELECTED",
        "PARTIAL_PASS_V21_092_R4_READY_WITH_DATA_WARN",
        "BLOCKED_V21_092_R4_LEAKAGE_OR_PROTECTED_MUTATION_RISK",
        "BLOCKED_V21_092_R4_REQUIRED_INPUTS_MISSING",
    }
    for col in ("research_only", "diagnostic_only", "shadow_only", "stress_test_only"):
        assert t(row[col])
    for col in ("official_ranking_mutated", "official_weights_mutated", "broker_action_created", "recommendation_created"):
        assert f(row[col])
    if row["final_status"] == "BLOCKED_V21_092_R4_REQUIRED_INPUTS_MISSING":
        assert str(row.get("missing_inputs", "")).strip()
        print("PASS test_v21_092_r4_micro_weight_shadow_stress_test_and_forward_plan_review")
        raise SystemExit(0)
    assert f(row["protected_outputs_modified"])
    for col in ("d_baseline_preserved", "technical_085_preserved", "fundamental_086_preserved", "interaction_087_preserved", "review_088_preserved", "monitor_089_preserved", "archive_090_preserved", "maturity_091_preserved", "shadow_search_092_r1_preserved", "stability_search_092_r2_preserved", "weight_effectiveness_092_r3_preserved"):
        assert t(row[col])
    assert f(row["official_adoption_allowed"]) and f(row["pullback_positive_weight_used"]) and f(row["day0_chase_used"]) and f(row["ma_slope_positive_weight_selected"])

    grid = pd.read_csv(out / MODULE.GRID_NAME)
    safe = pd.read_csv(ROOT / MODULE.SAFE_REL).set_index("factor_name")
    assert (grid[["RS_QQQ_micro_weight", "RS_SPY_micro_weight", "RS_SOXX_micro_weight"]] <= .0200001).all().all()
    assert (grid[["BreakoutConfirmation_micro_weight", "VolumeConfirmation_micro_weight"]] <= .0150001).all().all()
    assert (grid["LowQualityRisk_penalty_weight"] >= -.0100001).all()
    assert (grid["InteractionDataGap_penalty_weight"] >= -.0050001).all()
    assert (grid["OverextendedExposure_penalty_weight"] >= -.0100001).all()
    assert grid["MASlopeAlignment_positive_weight"].eq(0).all()
    assert grid["Pullback_positive_weight"].eq(0).all()
    assert grid["Day0Breakout_chase_weight"].eq(0).all()
    assert grid["official_adoption_allowed"].map(f).all()
    assert grid["forward_ledger_allowed_initial"].map(f).all()

    splits = pd.read_csv(ROOT / MODULE.SPLIT_REL)
    assert (splits["train_end"] < splits["validation_start"]).all()
    assert (splits["validation_end"] < splits["test_start"]).all()
    stress = pd.read_csv(out / MODULE.STRESS_NAME)
    assert set(stress["split_id"]).issubset(set(splits["split_id"]))

    forbidden = pd.read_csv(out / MODULE.FORBIDDEN_NAME)
    assert forbidden["positive_weight_allowed"].map(f).all()
    assert forbidden["tested_as_positive_weight"].map(f).all()
    assert forbidden["adoption_allowed"].map(f).all()

    selected = pd.read_csv(out / MODULE.SELECTED_NAME)
    assert selected.iloc[0]["selected_status"] in {"NO_MICRO_SHADOW_CANDIDATE_SELECTED", "MICRO_SHADOW_FORWARD_PLAN_CANDIDATE_DIAGNOSTIC_ONLY"}
    assert f(selected.iloc[0]["official_adoption_allowed"])
    assert f(selected.iloc[0]["broker_action_created"])
    assert f(selected.iloc[0]["recommendation_created"])
    assert t(selected.iloc[0]["no_trade_action_created"])
    plan = pd.read_csv(out / MODULE.FORWARD_NAME)
    assert plan["official_adoption_allowed"].map(f).all()
    assert plan["no_trade_action_created"].map(t).all()
    if selected.iloc[0]["selected_status"] == "NO_MICRO_SHADOW_CANDIDATE_SELECTED":
        assert plan["plan_status"].eq("NO_FORWARD_PLAN_CREATED").all()

    cert = pd.read_csv(out / MODULE.CERT_NAME)
    assert cert.iloc[0]["certification_status"] == "CERTIFIED_R4_MICRO_WEIGHT_STRESS_TEST_NO_ADOPTION_NO_TRADE"
    audit = pd.read_csv(out / MODULE.MUTATION_NAME, low_memory=False)
    assert not audit["modified_during_run"].map(t).any()
    assert result["final_status"] == row["final_status"]
    print("PASS test_v21_092_r4_micro_weight_shadow_stress_test_and_forward_plan_review")
