import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER"
REQ = [
    "cash_constrained_fallback_state.csv",
    "portfolio_mode_blockers_600usd.csv",
    "fallback_candidate_universe_600usd.csv",
    "fallback_candidate_feasibility_600usd.csv",
    "dram_hbm_nand_fallback_check_600usd.csv",
    "share_count_feasibility_600usd.csv",
    "single_name_exposure_scenarios_600usd.csv",
    "account_loss_budget_scenarios_600usd.csv",
    "fallback_vs_portfolio_separation.csv",
    "fallback_data_quality_warnings.csv",
    "fallback_policy_flags.csv",
    "protected_output_mutation_audit.csv",
    "V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER_report.txt",
    "V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER_summary.json",
]


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(OUT / name)


def summary() -> dict:
    return json.loads((OUT / "V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER_summary.json").read_text(encoding="utf-8"))


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
    assert s["fallback_adoption_allowed"] is False


def test_active_cash_budget_is_600():
    assert summary()["active_cash_budget_usd"] == 600


def test_portfolio_blocked_when_v167_r1_has_zero_executable_states():
    v167 = json.loads((ROOT / "outputs" / "v21" / "V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK" / "V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK_summary.json").read_text())
    if v167["active_600usd_executable_state_count"] == 0:
        assert summary()["portfolio_mode_blocked"] is True


def test_fallback_and_trading_flags_false():
    s = summary()
    assert s["fallback_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["live_trading_allowed"] is False
    assert s["official_adoption_allowed"] is False


def test_not_preference_and_not_diversified_flags():
    s = summary()
    assert s["not_user_preference_only_strategy"] is True
    assert s["not_diversified_portfolio"] is True


def test_dram_not_preference_or_diversified():
    state = read("cash_constrained_fallback_state.csv")
    assert "NOT_USER_PREFERENCE_ONLY_STRATEGY" in set(state["classification_state"])
    assert "NOT_DIVERSIFIED_PORTFOLIO" in set(state["classification_state"])
    sep = read("fallback_vs_portfolio_separation.csv")
    dram = sep[sep["mode"].eq("DRAM_HBM_NAND_FALLBACK")]
    assert len(dram) == 1
    assert dram["promoted"].astype(str).str.lower().iloc[0] == "false"


def test_share_count_and_loss_outputs_have_rows_if_priced_candidates_exist():
    s = summary()
    if s["priced_fallback_candidate_count"] > 0:
        assert len(read("share_count_feasibility_600usd.csv")) > 0
        assert len(read("account_loss_budget_scenarios_600usd.csv")) > 0


def test_fallback_vs_portfolio_separation_exists():
    df = read("fallback_vs_portfolio_separation.csv")
    assert len(df) > 0
    assert {"PORTFOLIO_MODE", "CASH_CONSTRAINED_FALLBACK_MODE"}.issubset(set(df["mode"]))


def test_output_directory_is_isolated():
    assert OUT.as_posix().endswith("outputs/v21/V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER")
    for path in OUT.iterdir():
        assert path.is_file()
        assert path.parent == OUT


def test_no_official_or_protected_outputs_modified():
    s = summary()
    audit = read("protected_output_mutation_audit.csv")
    assert s["protected_outputs_modified"] is False
    assert int(audit["changed_protected_file_count"].iloc[0]) == 0
