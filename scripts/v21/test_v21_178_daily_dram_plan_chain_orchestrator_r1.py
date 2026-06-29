import pandas as pd

from scripts.v21 import v21_178_daily_dram_plan_chain_orchestrator_r1 as m


def test_repaired_r1a_stale_warn_maps_to_active_stale_warn():
    action = m.consolidated_action("DRAM_TRADE_ALLOWED_LIMIT_ONLY", "LIMIT_PLAN_ALLOWED_WITH_STALE_WARNING", "RECENT_WARN", "STALE_WARN")
    assert action == "DRAM_DAILY_LIMIT_PLAN_ACTIVE_STALE_WARN"


def test_current_limit_plan_maps_to_active():
    action = m.consolidated_action("DRAM_TRADE_ALLOWED_LIMIT_ONLY", "LIMIT_PLAN_ALLOWED", "CURRENT", "CURRENT_OR_RECENT")
    assert action == "DRAM_DAILY_LIMIT_PLAN_ACTIVE"


def test_stale_block_maps_to_blocked_and_trade_false_inline():
    repaired = m.inline_semantic_repair({"staleness_status": "STALE_BLOCK", "trade_allowed_current": True}, pd.DataFrame())
    assert repaired["corrected_immediate_action_label"] == "STALE_DO_NOT_USE"
    assert repaired["corrected_trade_allowed_current"] is False
    action = m.consolidated_action("DRAM_TRADE_ALLOWED_LIMIT_ONLY", repaired["corrected_immediate_action_label"], repaired["trade_plan_currentness"], "STALE_BLOCK")
    assert action == "DRAM_DAILY_PLAN_STALE_BLOCKED"


def test_missing_v21_176_plan_blocks():
    status, decision = m.final_status_decision("DRAM_DAILY_PLAN_MISSING", True, ["MISSING_DAILY_PLAN"])
    assert status == "BLOCKED_V21_178_MISSING_DAILY_PLAN"
    assert decision == "DAILY_DRAM_CHAIN_BLOCKED_MISSING_PLAN"


def test_missing_r1c_price_blocks():
    status, decision = m.final_status_decision("DRAM_DAILY_DATA_MISSING", True, ["MISSING_DRAM_PRICE"])
    assert status == "BLOCKED_V21_178_MISSING_DRAM_PRICE"
    assert decision == "DAILY_DRAM_CHAIN_BLOCKED_MISSING_PRICE"


def test_inline_semantic_repair_applied_when_r1a_missing():
    repaired = m.inline_semantic_repair(
        {"staleness_status": "STALE_WARN", "latest_immediate_action_label": "LIMIT_PLAN_ALLOWED", "trade_allowed_current": True},
        pd.DataFrame(),
    )
    assert repaired["corrected_decision"] == "DAILY_DRAM_PLAN_LEDGER_ACTIVE_STALE_WARN"
    assert repaired["corrected_immediate_action_label"] == "LIMIT_PLAN_ALLOWED_WITH_STALE_WARNING"


def test_chain_health_table_reports_loaded_missing_stages():
    row = m.health_row("V21.176", False, {}, True, "missing")
    assert row["loaded"] is False
    assert row["blocking_issue"] is True
    row2 = m.health_row("V21.174_R1C", True, {"final_status": "PASS", "decision": "OK", "warnings": ["W"]}, False)
    assert row2["warning_count"] == 1


def test_hard_policy_flags_remain_locked():
    assert m.POLICY["research_only"] is True
    assert m.POLICY["official_adoption_allowed"] is False
    assert m.POLICY["broker_action_allowed"] is False
    assert m.POLICY["protected_outputs_modified"] is False
    assert m.POLICY["canonical_price_panel_modified"] is False


def test_daily_frequency_only_true_and_intraday_required_false():
    assert m.POLICY["daily_frequency_only"] is True
    assert m.POLICY["intraday_required"] is False
