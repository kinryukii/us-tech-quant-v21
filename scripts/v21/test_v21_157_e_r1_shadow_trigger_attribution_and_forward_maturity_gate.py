from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.157_E_R1_SHADOW_TRIGGER_ATTRIBUTION_AND_FORWARD_MATURITY_GATE")
REQ = [
    "input_discovery_report.csv",
    "e_r1_trigger_dates.csv",
    "e_r1_trigger_attribution_ledger.csv",
    "e_r1_trigger_score_decomposition.csv",
    "e_r1_trigger_quality_summary.csv",
    "e_r1_trigger_forward_outcomes.csv",
    "e_r1_trigger_forward_summary.csv",
    "e_r1_forward_maturity_gate.csv",
    "e_r1_defensive_benefit_vs_return_sacrifice.csv",
    "e_r1_role_review_gate_decision.csv",
    "V21.157_readable_report.txt",
    "V21.157_machine_summary.json",
]


def test_required_outputs_and_summary_fields() -> None:
    for name in REQ:
        assert (OUT / name).exists(), name
    s = json.loads((OUT / "V21.157_machine_summary.json").read_text(encoding="utf-8"))
    for key in [
        "FINAL_STATUS", "DECISION", "latest_price_date_used", "e_r1_trigger_date_count",
        "e_r1_trigger_rate", "trigger_quality", "overactive_trigger_warning",
        "matured_trigger_5D_count", "matured_trigger_10D_count", "matured_trigger_20D_count",
        "valid_paired_trigger_5D_count", "valid_paired_trigger_10D_count", "valid_paired_trigger_20D_count",
        "trigger_maturity_sufficient", "e_r1_left_tail_benefit_persisted_after_triggers",
        "e_r1_return_sacrifice_classification", "e_r1_role_review_ready",
        "governed_state_unchanged", "current_primary_control_unchanged", "research_only",
        "official_adoption_allowed", "broker_action_allowed", "protected_outputs_modified",
    ]:
        assert key in s


def test_v156_loaded_and_triggers_extracted() -> None:
    disc = pd.read_csv(OUT / "input_discovery_report.csv")
    assert disc[disc["source_name"].eq("shadow_candidate_state_by_date")]["usable"].astype(bool).iloc[0]
    triggers = pd.read_csv(OUT / "e_r1_trigger_dates.csv")
    assert not triggers.empty
    assert set(triggers["shadow_candidate_state"]) == {"STATE_DEFENSIVE_A1_E_R1"}


def test_trigger_attribution_risk_off_and_left_tail() -> None:
    decomp = pd.read_csv(OUT / "e_r1_trigger_score_decomposition.csv")
    risk = decomp[(decomp["score_name"].eq("risk_off_score")) & (decomp["triggered"].astype(bool))]
    assert not risk.empty
    assert "left_tail_risk_score" in set(decomp["score_name"])


def test_missing_optional_forward_keeps_wait() -> None:
    gate = pd.read_csv(OUT / "e_r1_forward_maturity_gate.csv").iloc[0]
    assert bool(gate["trigger_maturity_sufficient"]) is False
    decision = pd.read_csv(OUT / "e_r1_role_review_gate_decision.csv").iloc[0]
    assert decision["role_review_status"] == "WAIT_MORE_FORWARD_MATURITY"


def test_immature_not_counted_as_valid() -> None:
    fwd = pd.read_csv(OUT / "e_r1_trigger_forward_outcomes.csv")
    immature = fwd[fwd["maturity_status"].eq("immature")]
    if not immature.empty:
        assert (~immature["valid_paired_observation"].astype(bool)).all()


def test_no_adoption_or_governed_change() -> None:
    s = json.loads((OUT / "V21.157_machine_summary.json").read_text(encoding="utf-8"))
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["protected_outputs_modified"] is False
    assert s["governed_state_unchanged"] is True
    assert s["current_primary_control_unchanged"] is True


def test_role_review_ready_possible_logic_documented() -> None:
    decision = pd.read_csv(OUT / "e_r1_role_review_gate_decision.csv")
    assert "FINAL_STATUS" in decision.columns
    assert "DECISION" in decision.columns
