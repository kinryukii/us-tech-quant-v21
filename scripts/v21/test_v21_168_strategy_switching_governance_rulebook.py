import json
from pathlib import Path

import pandas as pd

from scripts.v21.v21_168_strategy_switching_governance_rulebook_r1 import main


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.168_STRATEGY_SWITCHING_GOVERNANCE_RULEBOOK_R1"
REQUIRED = [
    "switch_state_eligibility_matrix.csv",
    "switch_state_maturity_scoreboard.csv",
    "switch_state_risk_blocker_ledger.csv",
    "switch_state_execution_feasibility.csv",
    "switch_state_hysteresis_check.csv",
    "final_switch_recommendation.csv",
    "V21.168_switching_governance_report.txt",
    "validation_summary.json",
]
ALLOWED_FINAL_DECISIONS = {
    "KEEP_A1_CONTROL",
    "WAIT_MORE_MATURITY",
    "ALLOW_FORWARD_TRACKING_ONLY",
    "BLOCKED_BY_RISK",
    "BLOCKED_BY_EXECUTION",
    "BLOCKED_BY_DATA_QUALITY",
    "ROLE_REVIEW_REQUIRED",
    "SWITCH_ALLOWED_RESEARCH_ONLY",
    "OFFICIAL_ADOPTION_BLOCKED",
}


def setup_module():
    main()


def read_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(OUT / name)


def summary() -> dict:
    return json.loads((OUT / "validation_summary.json").read_text(encoding="utf-8"))


def test_required_outputs_exist():
    assert OUT.exists()
    for name in REQUIRED:
        assert (OUT / name).exists(), name


def test_final_decision_enum_and_policy_flags():
    s = summary()
    final = read_csv("final_switch_recommendation.csv")
    assert s["final_decision"] in ALLOWED_FINAL_DECISIONS
    assert final["final_decision"].iloc[0] in ALLOWED_FINAL_DECISIONS
    assert s["research_only"] is True
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert bool(final["research_only"].iloc[0]) is True
    assert bool(final["official_adoption_allowed"].iloc[0]) is False
    assert bool(final["broker_action_allowed"].iloc[0]) is False


def test_a1_control_retained_and_forward_state_tracked_only():
    eligibility = read_csv("switch_state_eligibility_matrix.csv")
    final = read_csv("final_switch_recommendation.csv")
    assert final["current_primary_control"].iloc[0] == "A1_CONTROL"
    a1 = eligibility[eligibility["state"].eq("A1_CONTROL")].iloc[0]
    assert a1["eligibility_class"] == "baseline"
    assert bool(a1["current_primary_control"]) is True
    main = eligibility[eligibility["state"].eq("A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING")].iloc[0]
    assert main["eligibility_class"] == "eligible_forward_tracking"
    assert bool(main["official_adoption_allowed"]) is False


def test_special_state_classifications():
    eligibility = read_csv("switch_state_eligibility_matrix.csv").set_index("state")
    assert eligibility.loc["D_ORIGINAL", "eligibility_class"] == "frozen_reference_only"
    assert eligibility.loc["D_R3_REBUILD", "eligibility_class"] == "blocked"
    assert eligibility.loc["A1_PLUS_SOFTCAP_WATCH_ONLY", "eligibility_class"] == "blocked_risk_mixed"
    assert eligibility.loc["A1_PLUS_E_R1_DEFENSIVE_STANDBY", "eligibility_class"] == "defensive_candidate"
    assert eligibility.loc["DRAM_ONLY", "eligibility_class"] == "execution_fallback_only"


def test_official_adoption_false_unless_all_gates_pass_not_expected():
    s = summary()
    hysteresis = read_csv("switch_state_hysteresis_check.csv")
    all_hysteresis_pass = hysteresis["hysteresis_gate_status"].astype(str).eq("PASS_ROLE_REVIEW_ELIGIBLE").all()
    execution = read_csv("switch_state_execution_feasibility.csv")
    any_execution_pass = execution["execution_gate_status"].astype(str).eq("PASS_EXECUTION_FEASIBLE").any()
    if not all_hysteresis_pass or not any_execution_pass:
        assert s["official_adoption_allowed"] is False
    assert s["official_adoption_allowed"] is False


def test_no_protected_outputs_modified():
    s = summary()
    assert s["protected_outputs_modified"] is False
    assert s["official_rankings_modified"] is False
    assert s["adopted_weights_modified"] is False
    assert s["changed_protected_file_count"] == 0
    assert s["protected_output_mutation_audit_clean"] is True


def test_missing_sources_are_warnings_not_silent_pass():
    risk = read_csv("switch_state_risk_blocker_ledger.csv")
    s = summary()
    assert s["source_warning_count"] >= 1
    assert "SOURCE_MISSING_WARNING" in set(risk["turnover_instability"].astype(str))
    assert not risk["turnover_instability"].astype(str).str.contains("PASS", case=False, na=False).any()


def test_maturity_wait_blocks_switch_when_no_matured_v21_164_rows():
    upstream = json.loads((ROOT / "outputs" / "v21" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR_summary.json").read_text(encoding="utf-8"))
    final = read_csv("final_switch_recommendation.csv")
    if int(upstream.get("matured_result_count_after", 0) or 0) == 0:
        assert final["final_decision"].iloc[0] in {"WAIT_MORE_MATURITY", "ALLOW_FORWARD_TRACKING_ONLY"}


def test_dram_only_execution_fallback_not_official_strategy():
    execution = read_csv("switch_state_execution_feasibility.csv")
    dram = execution[execution["state"].eq("DRAM_ONLY")]
    assert not dram.empty
    assert set(dram["eligibility_class"]) == {"execution_fallback_only"}
    assert not dram["official_portfolio_strategy"].astype(str).str.lower().isin(["true", "1"]).any()
    assert not dram["broker_action_allowed"].astype(str).str.lower().isin(["true", "1"]).any()
