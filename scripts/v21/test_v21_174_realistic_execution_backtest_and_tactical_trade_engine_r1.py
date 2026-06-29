import json
from pathlib import Path

import pandas as pd

from scripts.v21 import v21_174_realistic_execution_backtest_and_tactical_trade_engine_r1 as m


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / m.STAGE


def price_frame(rows):
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


def base_plan(**overrides):
    plan = {
        "trade_date": "2026-01-02",
        "ranking_date": "2026-01-01",
        "ticker": "TEST",
        "strategy_state": "UNIT",
        "planned_entry": 98.0,
        "no_chase_above": 103.0,
        "stop_loss": 95.0,
        "take_profit_1": 102.5,
        "take_profit_2": 105.5,
        "trade_allowed": True,
        "invalid_reason": "",
    }
    plan.update(overrides)
    return plan


def test_planned_entry_stop_loss_take_profit_calculations():
    levels = m.calculate_trade_levels(100.0, 4.0)
    assert levels["planned_entry"] == 98.6
    assert levels["no_chase_above"] == 103.0
    assert levels["stop_loss"] == 94.6
    assert levels["risk_per_share"] == 4.0
    assert levels["take_profit_1"] == 104.6
    assert levels["take_profit_2"] == 108.6
    assert levels["reward_risk_to_tp1"] == 1.5


def test_no_chase_rule_when_first_day_gaps_up_more_than_three_percent():
    path = price_frame(
        [
            {"date": "2026-01-02", "open": 104, "high": 106, "low": 103.5, "close": 105},
            {"date": "2026-01-03", "open": 105, "high": 106, "low": 104, "close": 105.5},
        ]
    )
    sim, _audit = m.simulate_trade(base_plan(), path, "5D", 5)
    assert sim["exit_reason"] == "NO_FILL"
    assert sim["missed_reason"] == "INVALID_NO_CHASE"


def test_no_fill_when_price_never_touches_planned_entry():
    path = price_frame([{"date": "2026-01-02", "open": 101, "high": 102, "low": 100, "close": 101}])
    sim, _audit = m.simulate_trade(base_plan(), path, "5D", 5)
    assert sim["filled"] is False
    assert sim["exit_reason"] == "NO_FILL"


def test_fill_when_daily_low_lte_entry_lte_high():
    path = price_frame([{"date": "2026-01-02", "open": 100, "high": 101, "low": 97, "close": 100}])
    sim, _audit = m.simulate_trade(base_plan(), path, "5D", 5)
    assert sim["filled"] is True
    assert sim["fill_price"] == 98.0
    assert sim["exit_reason"] == "HORIZON_EXIT"


def test_stop_loss_priority_when_stop_and_take_profit_both_hit_same_day():
    path = price_frame([{"date": "2026-01-02", "open": 98, "high": 106, "low": 94, "close": 100}])
    sim, audit = m.simulate_trade(base_plan(), path, "5D", 5)
    assert sim["exit_reason"] == "STOP_LOSS"
    assert sim["exit_price"] == 95.0
    assert audit[0]["same_bar_stop_and_tp_touched"] is True


def test_missed_trade_classification():
    plan = base_plan()
    assert m.classify_missed_trade({"missed_return_pct": 0.05, "missed_reason": ""}, plan) == "MISSED_WIN"
    assert m.classify_missed_trade({"missed_return_pct": -0.05, "missed_reason": ""}, plan) == "MISSED_LOSS"
    assert m.classify_missed_trade({"missed_return_pct": 0.0, "missed_reason": ""}, plan) == "MISSED_FLAT"
    assert m.classify_missed_trade({"missed_return_pct": 0.1, "missed_reason": "INVALID_NO_CHASE"}, plan) == "INVALID_NO_CHASE"


def test_dram_missing_should_warn_but_not_crash():
    candidates, warnings = m.build_candidates({}, {"TEST": pd.DataFrame()})
    assert candidates == []
    assert "WARN_DRAM_PRICE_OR_RANKING_MISSING" in warnings
    dram = m.generate_dram_plan({}, {"TEST": pd.DataFrame()})
    assert dram["final_decision"] == "DRAM_DATA_MISSING"


def test_hard_policy_flags_remain_enforced():
    assert m.POLICY["research_only"] is True
    assert m.POLICY["official_adoption_allowed"] is False
    assert m.POLICY["broker_action_allowed"] is False
    assert m.POLICY["protected_outputs_modified"] is False


def test_summary_json_schema_contains_all_required_fields():
    if not (OUT / "V21.174_execution_summary.json").exists():
        m.main()
    summary = json.loads((OUT / "V21.174_execution_summary.json").read_text(encoding="utf-8"))
    for field in m.SUMMARY_FIELDS:
        assert field in summary
    assert summary["research_only"] is True
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["protected_outputs_modified"] is False
