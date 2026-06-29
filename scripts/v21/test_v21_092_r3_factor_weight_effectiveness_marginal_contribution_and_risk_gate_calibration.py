#!/usr/bin/env python
from pathlib import Path
import importlib.util

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/v21/v21_092_r3_factor_weight_effectiveness_marginal_contribution_and_risk_gate_calibration.py"
SPEC = importlib.util.spec_from_file_location("v21_092_r3", MODULE_PATH)
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
        "PASS_V21_092_R3_WEIGHT_EFFECTIVENESS_MAP_READY",
        "PARTIAL_PASS_V21_092_R3_READY_WITH_DATA_WARN",
        "PARTIAL_PASS_V21_092_R3_NO_SAFE_WEIGHT_REGION_FOUND",
        "BLOCKED_V21_092_R3_LEAKAGE_OR_PROTECTED_MUTATION_RISK",
        "BLOCKED_V21_092_R3_REQUIRED_INPUTS_MISSING",
    }
    for col in ("research_only", "diagnostic_only", "shadow_only", "weight_effectiveness_only"):
        assert t(row[col])
    for col in ("official_ranking_mutated", "official_weights_mutated", "broker_action_created", "recommendation_created"):
        assert f(row[col])
    if row["final_status"] == "BLOCKED_V21_092_R3_REQUIRED_INPUTS_MISSING":
        assert str(row.get("missing_inputs", "")).strip()
        print("PASS test_v21_092_r3_factor_weight_effectiveness_marginal_contribution_and_risk_gate_calibration")
        raise SystemExit(0)
    assert row["final_status"].startswith(("PASS_", "PARTIAL_PASS_"))
    assert f(row["protected_outputs_modified"])
    for col in ("d_baseline_preserved", "technical_085_preserved", "fundamental_086_preserved", "interaction_087_preserved", "review_088_preserved", "monitor_089_preserved", "archive_090_preserved", "maturity_091_preserved", "shadow_search_092_r1_preserved", "stability_search_092_r2_preserved"):
        assert t(row[col])
    assert f(row["official_adoption_allowed"]) and f(row["pullback_positive_weight_used"]) and f(row["day0_chase_used"])

    allowed = pd.read_csv(out / MODULE.ALLOWED_NAME)
    pullback = allowed[allowed["factor_name"].isin(["z_tech_pullback_original", "z_tech_pullback_repaired_best"])]
    assert pullback["positive_weight_allowed"].map(f).all()
    one = pd.read_csv(out / MODULE.ONE_FACTOR_NAME)
    assert not one["factor_name"].isin(["z_tech_pullback_original", "z_tech_pullback_repaired_best", "TECH_BREAKOUT_DAY0_WATCH_ONLY"]).any()
    assert not ((one["factor_name"].str.contains("low_quality|interaction_data_gap", case=False, regex=True)) & (one["tested_weight"] > 0)).any()

    splits = pd.read_csv(ROOT / MODULE.SPLIT_REL)
    assert (splits["train_end"] < splits["validation_start"]).all()
    assert (splits["validation_end"] < splits["test_start"]).all()
    shrink = pd.read_csv(out / MODULE.SHRINKAGE_NAME)
    assert set(shrink["split_id"]).issubset(set(splits["split_id"]))

    gates = pd.read_csv(out / MODULE.GATE_NAME)
    assert gates["current_gate_threshold"].eq(-.30).all()
    assert set(gates["recommended_handling"]).issubset({
        "KEEP_GATE", "KEEP_GATE_REQUIRE_MORE_MATURITY",
        "REVIEW_GATE_DEFINITION_DIAGNOSTIC_ONLY", "DO_NOT_LOOSEN_GATE",
        "INVESTIGATE_OUTLIER_SPLIT", "ADD_RISK_PENALTY_BEFORE_RETEST",
    })
    forbidden = pd.read_csv(out / MODULE.FORBIDDEN_NAME)
    assert forbidden["positive_weight_allowed"].map(f).all()
    assert forbidden["tested_as_positive_weight"].map(f).all()
    assert forbidden["adoption_allowed"].map(f).all()

    selection = pd.read_csv(out / MODULE.SELECTION_NAME)
    assert selection.iloc[0]["selected_status"] in {"NO_SHADOW_CANDIDATE_SELECTED", "SHADOW_ONLY_FORWARD_LEDGER_CANDIDATE"}
    assert f(selection.iloc[0]["official_adoption_allowed"])
    assert f(selection.iloc[0]["broker_action_created"])
    assert f(selection.iloc[0]["recommendation_created"])
    assert t(selection.iloc[0]["no_trade_action_created"])

    risk = pd.read_csv(out / MODULE.RISK_SUMMARY_NAME)
    assert risk["adoption_allowed"].map(f).all()
    safe = pd.read_csv(out / MODULE.SAFE_MAP_NAME)
    assert safe["official_adoption_allowed"].map(f).all()
    cert = pd.read_csv(out / MODULE.CERT_NAME)
    assert cert.iloc[0]["certification_status"] == "CERTIFIED_R3_WEIGHT_EFFECTIVENESS_DIAGNOSTIC_NO_ADOPTION_NO_TRADE"
    audit = pd.read_csv(out / MODULE.MUTATION_NAME, low_memory=False)
    assert not audit["modified_during_run"].map(t).any()
    assert result["final_status"] == row["final_status"]
    print("PASS test_v21_092_r3_factor_weight_effectiveness_marginal_contribution_and_risk_gate_calibration")
