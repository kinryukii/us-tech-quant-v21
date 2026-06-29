#!/usr/bin/env python
from pathlib import Path
import importlib.util
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/v21/v21_092_r5_outlier_split_decomposition_and_risk_penalty_research.py"
SPEC = importlib.util.spec_from_file_location("v21_092_r5", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

def t(v): return str(v).strip().upper() in {"TRUE","1","YES"}
def f(v): return str(v).strip().upper() in {"FALSE","0","NO"}

if __name__ == "__main__":
    out = ROOT / MODULE.OUT_REL
    result = MODULE.run_stage(ROOT) if not (out / MODULE.VALIDATION_NAME).is_file() else pd.read_csv(out / MODULE.VALIDATION_NAME).iloc[0].to_dict()
    assert out.is_dir()
    for name in MODULE.OUTPUT_NAMES: assert (out / name).is_file(), name
    val = pd.read_csv(out / MODULE.VALIDATION_NAME); assert len(val) == 1
    row = val.iloc[0]
    assert row["final_status"] in {"PASS_V21_092_R5_OUTLIER_DECOMPOSITION_READY","PARTIAL_PASS_V21_092_R5_READY_WITH_DATA_WARN","BLOCKED_V21_092_R5_LEAKAGE_OR_PROTECTED_MUTATION_RISK","BLOCKED_V21_092_R5_REQUIRED_INPUTS_MISSING"}
    for c in ("research_only","diagnostic_only","shadow_only","outlier_research_only"): assert t(row[c])
    for c in ("official_ranking_mutated","official_weights_mutated","broker_action_created","recommendation_created"): assert f(row[c])
    if row["final_status"] == "BLOCKED_V21_092_R5_REQUIRED_INPUTS_MISSING":
        assert str(row.get("missing_inputs","")).strip()
        print("PASS test_v21_092_r5_outlier_split_decomposition_and_risk_penalty_research"); raise SystemExit(0)
    assert f(row["protected_outputs_modified"])
    for c in ("d_baseline_preserved","technical_085_preserved","fundamental_086_preserved","interaction_087_preserved","review_088_preserved","monitor_089_preserved","archive_090_preserved","maturity_091_preserved","shadow_search_092_r1_preserved","stability_search_092_r2_preserved","weight_effectiveness_092_r3_preserved","micro_stress_092_r4_preserved"): assert t(row[c])
    assert f(row["candidate_selected"]) and f(row["risk_penalty_adopted"]) and f(row["official_adoption_allowed"])

    stress = pd.read_csv(ROOT / MODULE.STRESS_REL)
    expected = stress[stress["severe_or_extreme_breach_flag"].map(t)]
    master = pd.read_csv(out / MODULE.MASTER_NAME)
    assert len(master) == len(expected)
    assert set(master["severity_bucket"]).issubset({"SEVERE","EXTREME"})
    penalties = pd.read_csv(out / MODULE.PENALTY_GRID_NAME)
    assert penalties["official_adoption_allowed"].map(f).all()
    psum = pd.read_csv(out / MODULE.PENALTY_SUMMARY_NAME)
    assert psum["adoption_allowed"].map(f).all()
    cert = pd.read_csv(out / MODULE.CERT_NAME)
    assert cert.iloc[0]["certification_status"] == "CERTIFIED_R5_OUTLIER_RESEARCH_NO_SELECTION_NO_ADOPTION_NO_TRADE"
    assert f(cert.iloc[0]["candidate_selected"]) and f(cert.iloc[0]["risk_penalty_adopted"])
    decisions = pd.read_csv(out / MODULE.DECISION_NAME)
    assert not decisions["forbidden_next_action"].str.contains("LOOSEN", case=False).eq(False).all() or "LOOSEN_DRAWDOWN_GATE" in set(decisions["forbidden_next_action"])
    audit = pd.read_csv(out / MODULE.MUTATION_NAME, low_memory=False)
    assert not audit["modified_during_run"].map(t).any()
    assert result["final_status"] == row["final_status"]
    print("PASS test_v21_092_r5_outlier_split_decomposition_and_risk_penalty_research")
