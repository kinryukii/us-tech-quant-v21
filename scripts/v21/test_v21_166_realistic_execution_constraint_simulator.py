import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR"
REQ = [
    "execution_constraint_config.csv",
    "state_level_executable_feasibility.csv",
    "ticker_level_executable_feasibility.csv",
    "cash_budget_sensitivity.csv",
    "single_name_concentration_risk.csv",
    "slippage_and_spread_assumption.csv",
    "event_gap_risk_flags.csv",
    "small_account_position_sizing_simulation.csv",
    "execution_blockers.csv",
    "protected_output_mutation_audit.csv",
    "V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR_report.txt",
    "V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR_summary.json",
]


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(OUT / name)


def summary() -> dict:
    return json.loads((OUT / "V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR_summary.json").read_text(encoding="utf-8"))


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
    assert s["execution_adoption_allowed"] is False


def test_state_level_feasibility_has_rows():
    df = read("state_level_executable_feasibility.csv")
    assert len(df) > 0
    assert "feasibility_status" in df.columns


def test_ticker_level_feasibility_has_rows():
    df = read("ticker_level_executable_feasibility.csv")
    assert len(df) > 0
    assert {"ticker", "whole_shares_simulated", "broker_action_allowed", "live_trading_allowed"}.issubset(df.columns)


def test_cash_budget_sensitivity_has_rows():
    df = read("cash_budget_sensitivity.csv")
    assert len(df) > 0
    assert "cash_budget_usd" in df.columns


def test_small_account_simulation_has_rows():
    df = read("small_account_position_sizing_simulation.csv")
    assert len(df) > 0
    assert {3, 5, 8}.issubset(set(pd.to_numeric(df["top_n"], errors="coerce").dropna().astype(int)))


def test_execution_blockers_file_exists():
    df = read("execution_blockers.csv")
    assert "blocker_type" in df.columns


def test_no_broker_or_live_flags_true():
    s = summary()
    assert s["broker_action_allowed"] is False
    assert s["live_trading_allowed"] is False
    ticker = read("ticker_level_executable_feasibility.csv")
    assert not ticker["broker_action_allowed"].astype(str).str.lower().eq("true").any()
    assert not ticker["live_trading_allowed"].astype(str).str.lower().eq("true").any()


def test_no_official_or_protected_output_files_modified():
    s = summary()
    audit = read("protected_output_mutation_audit.csv")
    assert s["protected_outputs_modified"] is False
    assert int(audit["changed_protected_file_count"].iloc[0]) == 0


def test_dram_unavailable_is_not_fabricated():
    s = summary()
    state = read("state_level_executable_feasibility.csv")
    dram = state[state["state"].eq("DRAM_ONLY_SCENARIO")]
    assert len(dram) > 0
    if s["dram_only_available"] is False:
        assert set(dram["feasibility_status"]) == {"DRAM_ONLY_UNAVAILABLE_MISSING_PRICE"}
        ticker = read("ticker_level_executable_feasibility.csv")
        assert "DRAM" not in set(ticker["ticker"].astype(str))


def test_output_directory_is_isolated():
    assert OUT.as_posix().endswith("outputs/v21/V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR")
    for path in OUT.iterdir():
        assert path.is_file()
        assert path.parent == OUT
