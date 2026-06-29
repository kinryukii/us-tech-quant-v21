import pandas as pd

from scripts.v21 import v21_177_daily_dram_plan_ledger_and_staleness_gate_r1 as m


def plan_row():
    return {
        "plan_date": "2026-06-26",
        "target_trade_session": "NEXT",
        "ticker": "DRAM",
        "latest_close": 71.0,
        "setup_classification": "DAILY_TREND_RECOVERY",
        "final_decision": "DRAM_TRADE_ALLOWED_LIMIT_ONLY",
        "position_mode": "LIMIT_ONLY",
        "planned_entry_base": 69.0,
        "planned_entry_conservative": 68.0,
        "no_chase_above": 74.0,
        "stop_loss_base": 63.0,
        "stop_loss_tight": 65.0,
        "take_profit_1_base": 78.0,
        "take_profit_2_base": 84.0,
        "trade_allowed_daily_plan": True,
        "invalid_reason": "",
        "next_required_condition": "limit only",
    }


def prices(rows):
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df["ticker"] = "DRAM"
    return df


def test_staleness_current_or_recent():
    assert m.staleness_status("2026-06-29", pd.Timestamp("2026-06-30")) == "CURRENT_OR_RECENT"


def test_staleness_warn():
    assert m.staleness_status("2026-06-26", pd.Timestamp("2026-06-30")) == "STALE_WARN"


def test_staleness_block():
    assert m.staleness_status("2026-06-20", pd.Timestamp("2026-06-30")) == "STALE_BLOCK"


def test_append_new_daily_plan_to_empty_ledger():
    row = m.build_ledger_row(pd.Series(plan_row()), "2026-06-26", "CURRENT_OR_RECENT", "ts", "id1")
    ledger, appended, dup = m.append_plan(pd.DataFrame(), row)
    assert appended is True
    assert dup is False
    assert len(ledger) == 1


def test_duplicate_daily_plan_skipped():
    row = m.build_ledger_row(pd.Series(plan_row()), "2026-06-26", "CURRENT_OR_RECENT", "ts", "id1")
    ledger, _, _ = m.append_plan(pd.DataFrame(), row)
    ledger2, appended, dup = m.append_plan(ledger, {**row, "ledger_id": "id2"})
    assert appended is False
    assert dup is True
    assert len(ledger2) == 1


def test_limit_only_fill_only_when_planned_entry_touched():
    row = pd.Series(m.build_ledger_row(pd.Series(plan_row()), "2026-06-26", "CURRENT_OR_RECENT", "ts", "id1"))
    px = prices([{"date": "2026-06-27", "open": 72, "high": 73, "low": 70, "close": 72}])
    out = m.evaluate_one(row, px)
    assert out["filled_within_1d"] is False


def test_same_day_stop_and_tp_prioritizes_stop():
    row = pd.Series(m.build_ledger_row(pd.Series(plan_row()), "2026-06-26", "CURRENT_OR_RECENT", "ts", "id1"))
    px = prices([{"date": "2026-06-27", "open": 69, "high": 85, "low": 62, "close": 70}])
    out = m.evaluate_one(row, px)
    assert out["filled_within_1d"] is True
    assert out["hit_stop_loss_within_5d"] is True
    assert out["hit_tp1_within_5d"] is False


def test_pending_maturity_when_insufficient_forward_bars():
    row = pd.Series(m.build_ledger_row(pd.Series(plan_row()), "2026-06-26", "CURRENT_OR_RECENT", "ts", "id1"))
    px = prices([{"date": "2026-06-27", "open": 69, "high": 70, "low": 68, "close": 69.5}])
    out = m.evaluate_one(row, px)
    assert out["outcome_5d_status"] == "PENDING_MATURITY"


def test_missed_win_flag_for_no_fill_followed_by_gt_3pct_5d_return():
    row = pd.Series(m.build_ledger_row(pd.Series(plan_row()), "2026-06-26", "CURRENT_OR_RECENT", "ts", "id1"))
    dates = pd.date_range("2026-06-27", periods=5, freq="D")
    px = prices([{"date": d, "open": 72, "high": 73+i, "low": 70, "close": 72 + i} for i, d in enumerate(dates)])
    out = m.evaluate_one(row, px)
    assert out["missed_win_flag"] is True


def test_avoided_loss_flag_for_no_fill_followed_by_negative_5d_return():
    row = pd.Series(m.build_ledger_row(pd.Series(plan_row()), "2026-06-26", "CURRENT_OR_RECENT", "ts", "id1"))
    dates = pd.date_range("2026-06-27", periods=5, freq="D")
    px = prices([{"date": d, "open": 72, "high": 73, "low": 70, "close": 68 - i} for i, d in enumerate(dates)])
    out = m.evaluate_one(row, px)
    assert out["avoided_loss_flag"] is True


def test_stale_block_sets_trade_allowed_current_false():
    row = m.build_ledger_row(pd.Series(plan_row()), "2026-06-20", "STALE_BLOCK", "ts", "id1")
    assert row["trade_allowed_current"] is False


def test_hard_policy_flags_remain_locked():
    assert m.POLICY["research_only"] is True
    assert m.POLICY["official_adoption_allowed"] is False
    assert m.POLICY["broker_action_allowed"] is False
    assert m.POLICY["protected_outputs_modified"] is False
    assert m.POLICY["canonical_price_panel_modified"] is False


def test_daily_frequency_only_true_and_intraday_required_false():
    assert m.POLICY["daily_frequency_only"] is True
    assert m.POLICY["intraday_required"] is False
