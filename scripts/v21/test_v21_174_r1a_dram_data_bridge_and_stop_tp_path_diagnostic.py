import json
from pathlib import Path

import pandas as pd

from scripts.v21 import v21_174_r1a_dram_data_bridge_and_stop_tp_path_diagnostic as m


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / m.STAGE


def test_dram_exact_ticker_detection_with_normalized_uppercase_symbol():
    exact, alias, matches, bdry = m.detect_dram_symbols(pd.Series([" dram ", "MU"]))
    assert exact is True
    assert alias is False
    assert matches == ["DRAM"]
    assert bdry is False


def test_dram_alias_detection():
    exact, alias, matches, _bdry = m.detect_dram_symbols(pd.Series(["DRAM.O", "BDRY"]))
    assert exact is False
    assert alias is True
    assert matches == ["DRAM.O"]


def test_empty_bridge_file_creation_when_no_usable_ohlcv_exists(tmp_path):
    created = m.create_bridge_file(pd.DataFrame(columns=m.BRIDGE_COLUMNS), tmp_path)
    assert created is False
    bridge = pd.read_csv(tmp_path / "dram_price_bridge_daily_ohlcv.csv")
    assert list(bridge.columns) == m.BRIDGE_COLUMNS
    assert bridge.empty


def test_isolated_bridge_creation_when_usable_ohlcv_exists(tmp_path):
    df = pd.DataFrame(
        [
            {"date": "2026-01-01", "ticker": "DRAM", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000},
        ]
    )
    created = m.create_bridge_file(df, tmp_path)
    assert created is True
    bridge = pd.read_csv(tmp_path / "dram_price_bridge_daily_ohlcv.csv")
    assert len(bridge) == 1
    assert bridge["ticker"].iloc[0] == "DRAM"


def test_stop_tp_integrity_audit_detects_missing_required_columns(tmp_path):
    pd.DataFrame({"ticker": ["A"]}).to_csv(tmp_path / "execution_trade_plan_ledger.csv", index=False)
    pd.DataFrame({"ticker": ["A"]}).to_csv(tmp_path / "execution_simulation_results.csv", index=False)
    pd.DataFrame().to_csv(tmp_path / "stop_take_profit_path_audit.csv", index=False)
    audit, _zero, passed = m.stop_tp_integrity_audit(tmp_path)
    assert passed is False
    assert not audit[audit["check_name"].eq("plan_required_columns_present")]["passed"].iloc[0]
    assert not audit[audit["check_name"].eq("simulation_required_columns_present")]["passed"].iloc[0]


def test_sensitivity_replay_produces_non_empty_summary_for_valid_plans():
    plan = pd.DataFrame(
        [
            {
                "ranking_date": "2026-01-01",
                "ticker": "TEST",
                "strategy_state": "UNIT",
                "planned_entry": 98.0,
                "no_chase_above": 103.0,
                "stop_loss": 95.0,
                "take_profit_1": 102.5,
                "take_profit_2": 105.5,
                "risk_per_share": 3.0,
                "trade_allowed": True,
                "invalid_reason": "",
            }
        ]
    )
    prices = {
        "TEST": pd.DataFrame(
            [
                {"date": pd.Timestamp("2026-01-02"), "open": 99, "high": 101, "low": 97, "close": 100},
                {"date": pd.Timestamp("2026-01-03"), "open": 100, "high": 103, "low": 99, "close": 102},
            ]
        )
    }
    summary, replay = m.replay_sensitivity(plan, prices)
    assert not summary.empty
    assert not replay.empty
    assert set(summary["variant"]) == {"BASE", "TIGHT", "WIDE"}


def test_same_day_stop_and_tp_still_prioritizes_stop():
    plan = pd.Series(
        {
            "ranking_date": "2026-01-01",
            "ticker": "TEST",
            "strategy_state": "UNIT",
            "planned_entry": 98.0,
            "no_chase_above": 103.0,
            "stop_loss": 95.0,
            "take_profit_1": 102.5,
            "take_profit_2": 105.5,
            "risk_per_share": 3.0,
            "trade_allowed": True,
            "invalid_reason": "",
        }
    )
    path = pd.DataFrame([{"date": pd.Timestamp("2026-01-02"), "open": 98, "high": 106, "low": 94, "close": 100}])
    sim, _audit = m.v174.simulate_trade(m.variant_plan(plan, "BASE"), path, "5D", 5)
    assert sim["exit_reason"] == "STOP_LOSS"


def test_hard_policy_flags_remain_locked():
    assert m.POLICY["research_only"] is True
    assert m.POLICY["official_adoption_allowed"] is False
    assert m.POLICY["broker_action_allowed"] is False
    assert m.POLICY["protected_outputs_modified"] is False
    assert m.POLICY["canonical_price_panel_modified"] is False


def test_missing_v21_174_outputs_produce_blocked_status(tmp_path):
    out = tmp_path / "out"
    m.main(tmp_path / "missing_prior", out)
    summary = json.loads((out / "V21.174_R1A_summary.json").read_text(encoding="utf-8"))
    assert summary["final_status"] == "BLOCKED_V21_174_R1A_MISSING_V21_174_OUTPUTS"
    assert summary["decision"] == "BLOCKED_MISSING_PRIOR_OUTPUTS"
