from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

P = Path(__file__).with_name("v21_253_coefficient_guided_e_r3_weight_recalibration.py")
S = importlib.util.spec_from_file_location("m253", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def wc(path: Path, data: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, lineterminator="\n")
        w.writeheader()
        w.writerows(data)


def wj(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def seed(repo: Path) -> Path:
    wj(repo / m.V252_R1_REL / "v21_252_r1_summary.json", {
        "sign_conflict_count": 2,
        "coefficient_guided_reweighting_ready": True,
        "repeated_loser_penalty_semantic_action": "increase_adjusted_score_weight",
        "left_tail_memory_semantic_action": "increase_adjusted_score_weight",
        "volatility_semantic_action": "cap_or_diagnostic_only",
        "gap_overnight_risk_semantic_action": "cap_or_diagnostic_only",
    })
    wc(repo / m.V252_R1_REL / "coefficient_guided_weight_action_input.csv", [
        {"factor_name": "KDJ", "factor_family": "Technical", "forward_window": "1D", "topn_scope": "20", "source_mode": "LIVE", "raw_beta_standardized": "-0.01", "factor_sign_convention": "higher_is_better", "semantic_effect_direction": "negative", "coefficient_guided_action": "wait_more_maturity", "sign_conflict": "False", "official_adoption_allowed": "False", "broker_action_allowed": "False"},
        {"factor_name": "volatility", "factor_family": "Risk", "forward_window": "1D", "topn_scope": "20", "source_mode": "LIVE", "raw_beta_standardized": "0.02", "factor_sign_convention": "higher_is_worse", "semantic_effect_direction": "conflict", "coefficient_guided_action": "cap_or_diagnostic_only", "sign_conflict": "True", "official_adoption_allowed": "False", "broker_action_allowed": "False"},
        {"factor_name": "repeated_loser_penalty", "factor_family": "Risk", "forward_window": "1D", "topn_scope": "20", "source_mode": "LIVE", "raw_beta_standardized": "0.02", "factor_sign_convention": "already_adjusted_score", "semantic_effect_direction": "positive", "coefficient_guided_action": "increase_adjusted_score_weight", "sign_conflict": "False", "official_adoption_allowed": "False", "broker_action_allowed": "False"},
        {"factor_name": "left_tail_memory_factor", "factor_family": "Risk", "forward_window": "1D", "topn_scope": "20", "source_mode": "LIVE", "raw_beta_standardized": "0.02", "factor_sign_convention": "already_adjusted_score", "semantic_effect_direction": "positive", "coefficient_guided_action": "increase_adjusted_score_weight", "sign_conflict": "False", "official_adoption_allowed": "False", "broker_action_allowed": "False"},
    ], ["factor_name", "factor_family", "forward_window", "topn_scope", "source_mode", "raw_beta_standardized", "factor_sign_convention", "semantic_effect_direction", "coefficient_guided_action", "sign_conflict", "official_adoption_allowed", "broker_action_allowed"])
    wc(repo / m.V252_REL / "factor_effect_coefficient_master.csv", [{"factor_name": "Risk"}], ["factor_name"])
    baseline = [
        ("Fundamental", "0.12"), ("Technical", "0.28"), ("Strategy", "0.18"), ("Risk", "0.27"), ("Market Regime", "0.10"), ("Data Trust", "0.05")
    ]
    wc(repo / m.V246_REL / "factor_weight_candidate_master.csv", [{"candidate": m.E_R2, "factor_family": f, "weight": w, "weights_sum": "1.0", "research_only": "True", "official_adoption_allowed": "False", "broker_action_allowed": "False"} for f, w in baseline], ["candidate", "factor_family", "weight", "weights_sum", "research_only", "official_adoption_allowed", "broker_action_allowed"])
    return repo / m.V246_REL / "factor_weight_candidate_master.csv"


def test_e_r3_candidates_constraints_and_safety(tmp_path):
    repo = tmp_path / "repo"
    prior = seed(repo)
    before = prior.read_bytes()
    summary = m.run(repo)
    out = repo / m.OUT_REL
    assert prior.read_bytes() == before
    assert summary["candidate_count"] == 5
    assert summary["family_weights_sum_to_one"] is True
    assert summary["bounded_deltas_applied"] is True
    assert summary["sign_conflict_protection_applied"] is True
    assert summary["kdj_upweighted"] is False
    assert summary["bollinger_band_upweighted"] is False
    assert summary["volume_upweighted"] is False
    assert summary["pullback_upweighted"] is False
    assert summary["volatility_cap_applied"] is True
    assert summary["gap_overnight_risk_cap_applied"] is True
    assert summary["repeated_loser_adjusted_score_weight_increased"] is True
    assert summary["left_tail_memory_adjusted_score_weight_increased"] is True
    assert summary["strategy_aggregate_blending_reduced"] is True
    assert summary["broker_action_allowed"] is False and summary["official_adoption_allowed"] is False
    rows = list(csv.DictReader((out / "e_r3_weight_candidate_master.csv").open("r", encoding="utf-8")))
    sums = {}
    for r in rows:
        sums.setdefault(r["candidate"], 0.0)
        sums[r["candidate"]] += float(r["weight"])
        assert abs(float(r["delta_vs_e_r2"])) <= 0.08
    assert all(abs(v - 1.0) < 1e-6 for v in sums.values())
    sub = (out / "e_r3_subfactor_weight_delta_audit.csv").read_text(encoding="utf-8")
    assert "KDJ" in sub and "ranking-alpha increase blocked" in sub
    assert "repeated_loser_penalty" in sub and "increase_adjusted_score_weight" in sub
    for name in ["e_r3_family_weight_delta_audit.csv", "e_r3_sign_conflict_protection_audit.csv", "e_r3_penalty_factor_semantic_application_audit.csv", "e_r3_candidate_definition.csv", "e_r3_candidate_risk_constraint_audit.csv", "v21_253_summary.json", "V21.253_coefficient_guided_e_r3_weight_recalibration_report.txt"]:
        assert (out / name).exists()


def test_missing_inputs_block(tmp_path):
    summary = m.run(tmp_path / "repo")
    assert summary["final_status"] == "FAIL_V21_253_E_R3_BLOCKED"
    assert summary["error_count"] == 1
