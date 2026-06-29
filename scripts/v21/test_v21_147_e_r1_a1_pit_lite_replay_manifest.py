import json
from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.147_E_R1_A1_PIT_LITE_REPLAY_MANIFEST")
REQUIRED = [
    "V21.147_summary.json",
    "V21.147_manifest_scope.csv",
    "V21.147_allowed_inputs_manifest.csv",
    "V21.147_forbidden_inputs_manifest.csv",
    "V21.147_date_sampling_rules.csv",
    "V21.147_ranking_reconstruction_assumptions.csv",
    "V21.147_v21_148_required_output_schema.csv",
    "V21.147_v21_148_decision_boundaries.csv",
    "V21.147_remaining_blockers.csv",
    "V21.147_readable_report.txt",
]


def summary():
    with (OUT / "V21.147_summary.json").open("r", encoding="utf-8") as f:
        return json.load(f)


def test_required_outputs_and_controls():
    assert OUT.exists()
    for name in REQUIRED:
        assert (OUT / name).exists(), name
    s = summary()
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["protected_outputs_modified"] is False
    assert s["strategy_adoption_allowed"] is False
    assert s["replay_execution_allowed"] is False
    assert s["pit_strict_claim_allowed"] is False


def test_manifests_and_sampling_rules_exist():
    allowed = pd.read_csv(OUT / "V21.147_allowed_inputs_manifest.csv")
    forbidden = pd.read_csv(OUT / "V21.147_forbidden_inputs_manifest.csv")
    dates = pd.read_csv(OUT / "V21.147_date_sampling_rules.csv")
    assert not allowed.empty
    assert not forbidden.empty
    assert not dates.empty
    assert {"path", "input_role", "exists", "allowed_usage"}.issubset(allowed.columns)
    assert "future factor values" in set(forbidden["forbidden_input"])


def test_reconstruction_assumptions_and_boundaries():
    assumptions = pd.read_csv(OUT / "V21.147_ranking_reconstruction_assumptions.csv")
    boundaries = pd.read_csv(OUT / "V21.147_v21_148_decision_boundaries.csv")
    assert {"A1_BASELINE_CONTROL", "E_R1_REPAIRED"}.issubset(set(assumptions["strategy"]))
    assert not boundaries.empty
    assert (boundaries[boundaries["decision_rule"].eq("may_authorize_adoption")]["allowed"] == False).all()
    assert (boundaries[boundaries["decision_rule"].eq("may_claim_PIT_STRICT")]["allowed"] == False).all()


def test_report_contains_status_and_decision():
    text = (OUT / "V21.147_readable_report.txt").read_text(encoding="utf-8")
    assert "FINAL_STATUS=" in text
    assert "DECISION=" in text
    s = summary()
    assert "FINAL_STATUS" in s
    assert "DECISION" in s
