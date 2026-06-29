#!/usr/bin/env python
from pathlib import Path
import importlib.util

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/v21/v21_092_r2_factor_filter_repair_and_weight_search_stability_tightening.py"
SPEC = importlib.util.spec_from_file_location("v21_092_r2", MODULE_PATH)
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
        "PASS_V21_092_R2_STABILITY_TIGHTENED_SHADOW_CANDIDATE_READY",
        "PARTIAL_PASS_V21_092_R2_STABILITY_TIGHTENED_NO_SHADOW_SELECTED",
        "PARTIAL_PASS_V21_092_R2_READY_WITH_DATA_WARN",
        "BLOCKED_V21_092_R2_LEAKAGE_OR_PROTECTED_MUTATION_RISK",
        "BLOCKED_V21_092_R2_REQUIRED_INPUTS_MISSING",
    }
    for col in ("research_only", "diagnostic_only", "shadow_only"):
        assert t(row[col])
    for col in ("official_ranking_mutated", "official_weights_mutated", "broker_action_created", "recommendation_created"):
        assert f(row[col])
    if row["final_status"] == "BLOCKED_V21_092_R2_REQUIRED_INPUTS_MISSING":
        assert str(row.get("missing_inputs", "")).strip()
        print("PASS test_v21_092_r2_factor_filter_repair_and_weight_search_stability_tightening")
        raise SystemExit(0)
    assert row["final_status"].startswith(("PASS_", "PARTIAL_PASS_"))
    assert f(row["protected_outputs_modified"])
    for col in ("d_baseline_preserved", "technical_085_preserved", "fundamental_086_preserved", "interaction_087_preserved", "review_088_preserved", "monitor_089_preserved", "archive_090_preserved", "maturity_091_preserved", "shadow_search_092_r1_preserved"):
        assert t(row[col])
    assert f(row["official_adoption_allowed"]) and f(row["pullback_positive_weight_used"]) and f(row["day0_chase_used"])

    r1 = pd.read_csv(ROOT / MODULE.RESULTS_R1_REL)
    forensic = pd.read_csv(out / MODULE.FORENSIC_NAME)
    assert set(r1.loc[~r1["drawdown_gate_pass"].map(t), "candidate_id"]).issubset(set(forensic["candidate_id"]))
    assert int(row["r1_drawdown_failures_reviewed"]) == int((~r1["drawdown_gate_pass"].map(t)).sum())

    filters = pd.read_csv(out / MODULE.FILTER_NAME)
    assert "z_tech_ma_slope_alignment" in set(filters["factor_name"])
    assert {"z_tech_rs_vs_qqq", "z_tech_rs_vs_spy", "z_tech_rs_vs_soxx"}.issubset(set(filters["factor_name"]))
    pullback = filters[filters["factor_name"].isin(["z_tech_pullback_original", "z_tech_pullback_repaired_best"])]
    assert pullback["factor_filter_status"].eq("BLACKLIST_FORBIDDEN").all()

    grid = pd.read_csv(out / MODULE.GRID_NAME)
    assert len(grid) <= 10
    assert grid["pullback_positive_weight_allowed"].map(f).all()
    assert grid["day0_chase_allowed"].map(f).all()
    assert grid["official_adoption_allowed"].map(f).all()
    assert (grid["PullbackPenalty"] <= 0).all()
    assert (grid["RiskPenalty"] < 0).all()
    assert (grid["max_weight_delta_vs_D"] <= .0500001).all()

    splits = pd.read_csv(ROOT / MODULE.SPLIT_REL)
    assert (splits["train_end"] < splits["validation_start"]).all()
    assert (splits["validation_end"] < splits["test_start"]).all()
    results = pd.read_csv(out / MODULE.RESULTS_NAME)
    assert set(results["split_id"]).issubset(set(splits["split_id"]))
    assert not results["leakage_warning"].fillna("").astype(str).str.strip().ne("").any()

    forbidden = pd.read_csv(out / MODULE.FORBIDDEN_NAME)
    assert forbidden["positive_weight_allowed"].map(f).all()
    assert forbidden["used_as_positive_weight"].map(f).all()
    assert forbidden["adoption_allowed"].map(f).all()

    selected = pd.read_csv(out / MODULE.SELECTED_NAME)
    assert len(selected) == 1
    assert selected.iloc[0]["selected_status"] in {"SHADOW_ONLY_FORWARD_LEDGER_CANDIDATE", "NO_SHADOW_CANDIDATE_SELECTED"}
    assert f(selected.iloc[0]["official_adoption_allowed"]) and f(selected.iloc[0]["broker_action_created"])
    ledger = pd.read_csv(out / MODULE.LEDGER_NAME)
    if not ledger.empty:
        assert selected.iloc[0]["selected_status"] == "SHADOW_ONLY_FORWARD_LEDGER_CANDIDATE"
        assert ledger["official_adoption_allowed"].map(f).all()
        assert ledger["no_trade_action_created"].map(t).all()

    cert = pd.read_csv(out / MODULE.CERT_NAME)
    assert cert.iloc[0]["certification_status"] == "CERTIFIED_R2_STABILITY_TIGHTENED_SHADOW_SEARCH_NO_ADOPTION_NO_TRADE"
    audit = pd.read_csv(out / MODULE.MUTATION_NAME, low_memory=False)
    assert not audit["modified_during_run"].map(t).any()
    assert result["final_status"] == row["final_status"]
    print("PASS test_v21_092_r2_factor_filter_repair_and_weight_search_stability_tightening")
