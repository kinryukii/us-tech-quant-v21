from types import SimpleNamespace

import pandas as pd

from scripts.v21 import v21_178_r1a_daily_dram_chain_execution_mode as m


def test_child_command_success_audit():
    def runner(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    row = m.run_child("X", "script.ps1", runner)
    assert row["attempted"] is True
    assert row["success"] is True
    assert row["blocking_issue"] is False


def test_child_command_failure_captured_as_warning():
    def runner(*_args, **_kwargs):
        return SimpleNamespace(returncode=2, stdout="bad", stderr="err")

    row = m.run_child("X", "script.ps1", runner)
    assert row["success"] is False
    assert row["blocking_issue"] is True
    assert "CHILD_STAGE_FAILED_CAPTURED" in row["notes"]


def test_pre_post_freshness_comparison_detects_changed_latest_price_date():
    df = m.compare_freshness({"latest_price_date": "2026-06-26", "latest_plan_date": "2026-06-26"}, {"latest_price_date": "2026-06-30", "latest_plan_date": "2026-06-26"})
    assert bool(df[df["field"].eq("latest_price_date")]["changed"].iloc[0]) is True
    assert bool(df[df["field"].eq("latest_plan_date")]["changed"].iloc[0]) is False


def test_final_decision_copy_includes_execution_mode_flags():
    final = pd.DataFrame([{"ticker": "DRAM", "latest_price_date": "2026-06-26"}])
    comp = m.compare_freshness({"latest_price_date": "2026-06-26", "latest_plan_date": "2026-06-26"}, {"latest_price_date": "2026-06-30", "latest_plan_date": "2026-06-30"})
    out = m.final_copy(final, True, comp)
    assert bool(out["execution_mode"].iloc[0]) is True
    assert bool(out["child_chain_executed"].iloc[0]) is True
    assert bool(out["all_required_children_success"].iloc[0]) is True
    assert bool(out["refresh_attempted"].iloc[0]) is True
    assert bool(out["refresh_improved_latest_price_date"].iloc[0]) is True


def test_hard_policy_flags_remain_locked():
    assert m.POLICY["research_only"] is True
    assert m.POLICY["official_adoption_allowed"] is False
    assert m.POLICY["broker_action_allowed"] is False
    assert m.POLICY["protected_outputs_modified"] is False
    assert m.POLICY["canonical_price_panel_modified"] is False


def test_daily_frequency_only_true_and_intraday_required_false():
    assert m.POLICY["daily_frequency_only"] is True
    assert m.POLICY["intraday_required"] is False


def test_final_decision_missing_after_execution_returns_blocked():
    status, decision = m.status_decision(True, False, {})
    assert status == "BLOCKED_V21_178_R1A_FINAL_DECISION_MISSING"
    assert decision == "DAILY_DRAM_EXECUTION_CHAIN_BLOCKED_NO_FINAL_DECISION"


def test_stale_warn_after_successful_execution_returns_partial_pass():
    status, decision = m.status_decision(True, True, {"consolidated_action_label": "DRAM_DAILY_LIMIT_PLAN_ACTIVE_STALE_WARN", "refresh_required": True})
    assert status == "PARTIAL_PASS_V21_178_R1A_EXECUTION_CHAIN_READY_STALE_WARN"
    assert decision == "DAILY_DRAM_EXECUTION_CHAIN_READY_REFRESH_STILL_RECOMMENDED"
