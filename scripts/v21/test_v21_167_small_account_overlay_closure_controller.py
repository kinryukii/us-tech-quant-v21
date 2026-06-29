import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.167_SMALL_ACCOUNT_OVERLAY_CLOSURE_CONTROLLER"
REQ = [
    "small_account_overlay_state.csv",
    "softcap_small_account_feasibility.csv",
    "e_r1_small_account_feasibility.csv",
    "dram_only_small_account_feasibility.csv",
    "overlay_execution_closure_decision.csv",
    "small_account_overlay_blockers.csv",
    "small_account_overlay_risk_budget.csv",
    "small_account_overlay_regime_mapping.csv",
    "small_account_overlay_forward_tracking_plan.csv",
    "small_account_overlay_data_quality_warnings.csv",
    "protected_output_mutation_audit.csv",
    "V21.167_SMALL_ACCOUNT_OVERLAY_CLOSURE_CONTROLLER_report.txt",
    "V21.167_SMALL_ACCOUNT_OVERLAY_CLOSURE_CONTROLLER_summary.json",
]


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(OUT / name)


def summary() -> dict:
    return json.loads((OUT / "V21.167_SMALL_ACCOUNT_OVERLAY_CLOSURE_CONTROLLER_summary.json").read_text(encoding="utf-8"))


def test_required_outputs_and_summary_exist():
    assert OUT.exists()
    for name in REQ:
        assert (OUT / name).exists(), name
    assert "final_status" in summary()


def test_policy_flags_remain_enforced():
    s = summary()
    assert s["research_only"] is True
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["live_trading_allowed"] is False
    assert s["protected_outputs_modified"] is False
    assert s["role_review_required"] is False
    assert s["overlay_adoption_allowed"] is False


def test_a1_primary_small_account_reference_exists():
    df = read("small_account_overlay_state.csv")
    row = df[df["module"].eq("A1_PRIMARY_CONTROL")]
    assert len(row) == 1
    assert row["classification_state"].iloc[0] == "A1_PRIMARY_SMALL_ACCOUNT_REFERENCE"


def test_softcap_feasibility_output_exists():
    df = read("softcap_small_account_feasibility.csv")
    assert len(df) > 0
    assert "small_account_feasible" in df.columns


def test_e_r1_feasibility_output_exists():
    df = read("e_r1_small_account_feasibility.csv")
    assert len(df) > 0
    assert "small_account_feasible" in df.columns


def test_dram_only_feasibility_output_exists():
    df = read("dram_only_small_account_feasibility.csv")
    assert len(df) > 0
    assert "small_account_feasible" in df.columns


def test_overlay_closure_decision_output_exists():
    df = read("overlay_execution_closure_decision.csv")
    assert len(df) == 1
    assert "overlay_promotion_allowed" in df.columns


def test_if_maturity_unavailable_overlay_promotion_false():
    s = summary()
    if s["maturity_evidence_available"] is False:
        assert s["overlay_promotion_allowed"] is False


def test_if_dram_concentration_blocked_not_executable():
    s = summary()
    if s["dram_only_status"] == "DRAM_ONLY_RESEARCH_VIEW_EXECUTION_BLOCKED":
        assert s["dram_only_small_account_feasible"] is False


def test_no_broker_live_or_official_flags_true():
    s = summary()
    assert s["broker_action_allowed"] is False
    assert s["live_trading_allowed"] is False
    assert s["official_adoption_allowed"] is False
    for name in ["small_account_overlay_state.csv", "overlay_execution_closure_decision.csv"]:
        df = read(name)
        for col in ["broker_action_allowed", "live_trading_allowed", "official_adoption_allowed"]:
            assert not df[col].astype(str).str.lower().eq("true").any()


def test_output_directory_is_isolated():
    assert OUT.as_posix().endswith("outputs/v21/V21.167_SMALL_ACCOUNT_OVERLAY_CLOSURE_CONTROLLER")
    for path in OUT.iterdir():
        assert path.is_file()
        assert path.parent == OUT


def test_no_official_or_protected_output_files_modified():
    s = summary()
    audit = read("protected_output_mutation_audit.csv")
    assert s["protected_outputs_modified"] is False
    assert int(audit["changed_protected_file_count"].iloc[0]) == 0
