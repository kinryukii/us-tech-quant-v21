import json

import pandas as pd

from scripts.v21 import v21_177_r1a_staleness_semantic_repair as m


def test_stale_warn_maps_to_active_stale_warn_not_do_not_use():
    r = m.repair_semantics("STALE_WARN", "DAILY_DRAM_PLAN_STALE_DO_NOT_USE", True, "LIMIT_PLAN_ALLOWED", "DRAM_TRADE_ALLOWED_LIMIT_ONLY")
    assert r["corrected_decision"] == "DAILY_DRAM_PLAN_LEDGER_ACTIVE_STALE_WARN"
    assert r["corrected_decision"] != "DAILY_DRAM_PLAN_STALE_DO_NOT_USE"


def test_stale_warn_limit_allowed_maps_to_stale_warning_action():
    r = m.repair_semantics("STALE_WARN", "DAILY_DRAM_PLAN_STALE_DO_NOT_USE", True, "LIMIT_PLAN_ALLOWED", "DRAM_TRADE_ALLOWED_LIMIT_ONLY")
    assert r["immediate_action_label_corrected"] == "LIMIT_PLAN_ALLOWED_WITH_STALE_WARNING"


def test_stale_block_maps_to_do_not_use_and_trade_not_allowed():
    r = m.repair_semantics("STALE_BLOCK", "ANY", True, "LIMIT_PLAN_ALLOWED", "DRAM_TRADE_ALLOWED_LIMIT_ONLY")
    assert r["corrected_decision"] == "DAILY_DRAM_PLAN_STALE_DO_NOT_USE"
    assert r["trade_allowed_current_corrected"] is False
    assert r["immediate_action_label_corrected"] == "STALE_DO_NOT_USE"


def test_current_or_recent_maps_to_active_current_semantics():
    r = m.repair_semantics("CURRENT_OR_RECENT", "OLD", True, "LIMIT_PLAN_ALLOWED", "DRAM_TRADE_ALLOWED_LIMIT_ONLY")
    assert r["corrected_decision"] == "DAILY_DRAM_PLAN_LEDGER_ACTIVE"
    assert r["trade_plan_currentness"] == "CURRENT"
    assert r["refresh_required"] is False


def test_semantic_inconsistency_detected_for_stale_warn_do_not_use():
    assert m.inconsistency_detected("STALE_WARN", "DAILY_DRAM_PLAN_STALE_DO_NOT_USE") is True
    assert m.inconsistency_detected("STALE_BLOCK", "DAILY_DRAM_PLAN_STALE_DO_NOT_USE") is False


def test_hard_policy_flags_remain_locked():
    assert m.POLICY["research_only"] is True
    assert m.POLICY["official_adoption_allowed"] is False
    assert m.POLICY["broker_action_allowed"] is False
    assert m.POLICY["protected_outputs_modified"] is False
    assert m.POLICY["canonical_price_panel_modified"] is False
    assert m.POLICY["daily_frequency_only"] is True
    assert m.POLICY["intraday_required"] is False


def test_missing_v21_177_outputs_returns_blocked_status(tmp_path):
    out = tmp_path / "out"
    missing = tmp_path / "missing.json"
    m.main(out, missing, tmp_path / "missing_review.csv", tmp_path / "missing_ledger.csv")
    s = json.loads((out / "V21.177_R1A_summary.json").read_text(encoding="utf-8"))
    assert s["final_status"] == "BLOCKED_V21_177_R1A_MISSING_V21_177_OUTPUTS"
    assert s["decision"] == "STALENESS_SEMANTIC_REPAIR_BLOCKED_MISSING_INPUTS"
