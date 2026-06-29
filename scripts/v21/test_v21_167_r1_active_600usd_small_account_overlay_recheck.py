import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK"
REQ = [
    "active_600usd_overlay_state.csv",
    "active_600usd_top3_top5_feasibility.csv",
    "active_600usd_single_name_cap_check.csv",
    "active_600usd_theme_sleeve_cap_check.csv",
    "active_600usd_dram_only_concentration_check.csv",
    "active_600usd_leftover_cash.csv",
    "active_600usd_overlay_blockers.csv",
    "active_600usd_overlay_closure_decision.csv",
    "active_600usd_forward_tracking_plan.csv",
    "active_600usd_data_quality_warnings.csv",
    "protected_output_mutation_audit.csv",
    "V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK_report.txt",
    "V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK_summary.json",
]


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(OUT / name)


def summary() -> dict:
    return json.loads((OUT / "V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK_summary.json").read_text(encoding="utf-8"))


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


def test_active_cash_and_caps():
    s = summary()
    assert s["active_cash_budget_usd"] == 600
    assert s["max_single_name_dollar_cap"] == 210
    assert s["max_theme_sleeve_dollar_cap"] == 150


def test_active_600usd_closure_decision_output_exists():
    df = read("active_600usd_overlay_closure_decision.csv")
    assert len(df) == 1
    assert "overlay_promotion_allowed" in df.columns


def test_dram_only_feasibility_output_exists():
    df = read("active_600usd_dram_only_concentration_check.csv")
    assert len(df) > 0
    assert "active_600usd_executable" in df.columns


def test_if_dram_concentration_blocked_not_executable():
    s = summary()
    if s["dram_only_status_600usd"] == "DRAM_ONLY_RESEARCH_VIEW_EXECUTION_BLOCKED_BY_CONCENTRATION_600USD":
        assert s["dram_only_small_account_feasible_600usd"] is False


def test_if_maturity_unavailable_overlay_promotion_false():
    s = summary()
    if s["maturity_evidence_available"] is False:
        assert s["overlay_promotion_allowed"] is False


def test_no_broker_live_official_adoption_flags_true():
    s = summary()
    for key in ["broker_action_allowed", "live_trading_allowed", "official_adoption_allowed", "overlay_adoption_allowed"]:
        assert s[key] is False
    for name in ["active_600usd_overlay_state.csv", "active_600usd_overlay_closure_decision.csv"]:
        df = read(name)
        for col in ["broker_action_allowed", "live_trading_allowed", "official_adoption_allowed", "overlay_adoption_allowed"]:
            assert not df[col].astype(str).str.lower().eq("true").any()


def test_output_directory_is_isolated():
    assert OUT.as_posix().endswith("outputs/v21/V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK")
    for path in OUT.iterdir():
        assert path.is_file()
        assert path.parent == OUT


def test_no_official_or_protected_outputs_modified():
    s = summary()
    audit = read("protected_output_mutation_audit.csv")
    assert s["protected_outputs_modified"] is False
    assert int(audit["changed_protected_file_count"].iloc[0]) == 0
