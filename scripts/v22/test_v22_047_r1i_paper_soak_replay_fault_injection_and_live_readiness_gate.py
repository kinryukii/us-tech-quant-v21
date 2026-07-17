from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path); assert spec and spec.loader
    module = importlib.util.module_from_spec(spec); sys.modules[name] = module; spec.loader.exec_module(module); return module


i = load(HERE / "v22_047_r1i_paper_soak_replay_fault_injection_and_live_readiness_gate.py", "r1i_test")
h = load(HERE / "v22_047_r1h_paper_execution_order_lifecycle_and_reconciliation.py", "r1h_for_r1i_test")


@pytest.fixture
def r1i_repo(tmp_path):
    scripts = tmp_path / "scripts" / "v22"; config = tmp_path / "config"
    scripts.mkdir(parents=True); config.mkdir()
    for name in ("v22_047_r1i_paper_soak_replay_fault_injection_and_live_readiness_gate.py", "v22_047_r1h_paper_execution_order_lifecycle_and_reconciliation.py", "v22_047_r1b_strategy_plugin_template.py"):
        shutil.copy2(HERE / name, scripts)
    for name in ("v22_047_r1i_soak_replay_gate.json", "v22_047_r1h_paper_execution.json"):
        shutil.copy2(REPO / "config" / name, config)
    engine = h.PaperExecutionEngine(tmp_path); paths = i.Paths(tmp_path); i.ensure_outputs(paths)
    return tmp_path, paths, engine


def et(hour=10, minute=0): return datetime(2026, 7, 14, hour, minute, tzinfo=ZoneInfo("America/New_York"))


def arm(engine, now=None):
    return h.request_paper_arm(engine.paths, dashboard_clicked=True, first_confirmation=True,
                               second_confirmation="CONFIRM_PAPER_SIMULATED_TRADING_ONLY", current=now or et())


def submit(engine, intent="soak-1", **kw):
    data = dict(intent_id=intent, symbol="US.QQQ", side="BUY", decimal_quantity="1.000", limit_price="100", current=et())
    data.update(kw); return engine.submit_order(**data)


def digest_tree(path: Path):
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest() for p in path.rglob("*") if p.is_file()}


def test_no_order_soak_day_passes(r1i_repo):
    _, paths, _ = r1i_repo; i.start_soak_session(paths, et(9, 20), opend_ready_et=et(9, 25).isoformat(), strategy_decision_et=et(9, 45).isoformat())
    row = i.finish_soak_session(paths, et(16, 0))
    assert row["final_session_status"] == "HEALTHY_NO_ORDERS" and row["order_intent_count"] == 0


def test_completed_soak_day_recorded(r1i_repo):
    _, paths, engine = r1i_repo; i.start_soak_session(paths, et(9, 20)); arm(engine); submit(engine)
    engine.process_quote("soak-1", {"bid": "99", "ask": "99.5", "timestamp": et()}, current=et())
    row = i.finish_soak_session(paths, et(16, 0)); history = i._csv_rows(paths.soak_history)
    assert row["final_session_status"] == "HEALTHY" and row["filled_order_count"] == 1 and len(history) == 1


def test_failed_reconciliation_blocks_next_paper_session(r1i_repo):
    _, paths, engine = r1i_repo; i.start_soak_session(paths, et(9, 20))
    rec = {"session_status": "FAILED_RECONCILIATION", "paper_nav": "100000", "reconciled_at_et": et(16, 0).isoformat()}
    i.finish_soak_session(paths, et(16, 0), reconciliation=rec); state = i.read_json(paths.soak_state)
    assert state["next_session_paper_allowed"] is False and state["reconciliation_failure_count"] == 1
    with pytest.raises(h.R1HError, match="FAILED_RECONCILIATION"):
        arm(engine, et(10, 0) + timedelta(days=1))


def test_duplicate_broker_event_deduplicated(r1i_repo):
    _, paths, _ = r1i_repo; d = i.EventDeduplicator(paths)
    assert d.accept("broker", "event-1") is True and d.accept("broker", "event-1") is False
    _, report, _ = i.write_dedup_reports(paths); assert report["accepted_event_count"] == 1 and report["duplicate_event_count"] == 1


def test_duplicate_deal_event_deduplicated(r1i_repo):
    _, paths, _ = r1i_repo; d = i.EventDeduplicator(paths)
    assert d.accept("deal", "deal-1") is True and d.accept("deal", "deal-1") is False
    _, _, report = i.write_dedup_reports(paths); assert report["accepted_event_count"] == 1 and report["duplicate_position_increase_count"] == 0


def test_restart_after_submit_does_not_duplicate_order(r1i_repo):
    repo, _, engine = r1i_repo; arm(engine); submit(engine); restarted = h.PaperExecutionEngine(repo); replay = submit(restarted)
    assert replay["idempotent_replay"] is True and len(h.jsonl_rows(engine.paths.idempotency)) == 1


def test_restart_after_partial_fill_preserves_remaining_quantity(r1i_repo):
    repo, _, engine = r1i_repo; arm(engine); submit(engine); engine.process_quote("soak-1", {"bid": "99", "ask": "99.5", "timestamp": et()}, current=et(), max_fill_quantity="0.400")
    restarted = h.PaperExecutionEngine(repo); assert restarted._orders()["soak-1"]["remaining_quantity"] == "0.6"


def test_authorization_expiry_disarms_paper(r1i_repo):
    _, _, engine = r1i_repo; arm(engine); state = h.authorization_state(engine.paths, et(10, 31))
    assert state["execution_mode"] == "SHADOW" and state["execution_authorization"] == "DISARMED"


def test_startup_always_resets_shadow_disarmed(r1i_repo):
    _, paths, engine = r1i_repo; arm(engine); state = i.startup_reset(paths, et(10, 1))
    assert state["execution_mode"] == "SHADOW" and state["execution_authorization"] == "DISARMED"


def test_1550_clears_day_orders(r1i_repo):
    _, _, engine = r1i_repo; arm(engine, et(15, 49)); submit(engine, current=et(15, 49)); engine.expire_day_orders(et(15, 50))
    assert engine._orders()["soak-1"]["status"] == "EXPIRED" and h.read_json(engine.paths.cash)["reserved_cash"] == "0"


@pytest.mark.parametrize("symbol,asset", [("US.QQQ260117C00100000", "OPTION"), ("US.AAPL", "STOCK")])
def test_protected_assets_remain_untouched(r1i_repo, symbol, asset):
    _, paths, _ = r1i_repo; result = i.record_manual_operation(paths, symbol, asset, "BUY", et())
    assert result["protected_read_only"] is True and result["protected_asset_action_count"] == 0


def test_manual_operation_takes_priority_and_next_day_cooldown(r1i_repo):
    _, paths, engine = r1i_repo; arm(engine); submit(engine); result = i.record_manual_operation(paths, "US.QQQ", "ETF", "BUY", et(10, 1))
    assert result["manual_operation_priority"] and engine._orders()["soak-1"]["status"] == "CANCELED"
    assert i.participation_allowed(paths, "US.QQQ", et(15, 0)) is False
    blocked = submit(engine, "soak-2", current=et(10, 2)); assert blocked["status"] == "REJECTED" and blocked["reason_code"] == "MANUAL_OPERATION_COOLDOWN_ACTIVE"
    assert i.participation_allowed(paths, "US.QQQ", et(9, 45) + timedelta(days=1)) is True
    assert i.read_json(paths.manual_state)["normal_manual_activity_degraded"] is False


def test_explicit_resume_ends_manual_cooldown(r1i_repo):
    _, paths, _ = r1i_repo; i.record_manual_operation(paths, "US.QQQ", "ETF", "SELL", et())
    i.explicit_resume(paths, "US.QQQ", et(10, 1)); assert i.participation_allowed(paths, "US.QQQ", et(10, 2)) is True


def test_replay_does_not_modify_production_ledgers(r1i_repo):
    _, paths, _ = r1i_repo; before = digest_tree(paths.r1h_output); first = i.run_replay_suite(paths); after = digest_tree(paths.r1h_output); second = i.run_replay_suite(paths)
    assert before == after and first == second and len(first) == 25


def test_fault_injection_disabled_in_production(r1i_repo):
    _, paths, _ = r1i_repo; injector = i.FaultInjector(test_mode=False, enabled=True)
    for point in i.FAULT_POINTS: injector.trigger(point)
    assert i.load_config(paths)["fault_injection_enabled"] is False


def test_fault_injection_only_triggers_in_test_mode():
    with pytest.raises(i.InjectedFault, match="FAIL_AFTER_SUBMIT"):
        i.FaultInjector(test_mode=True, enabled=True).trigger("FAIL_AFTER_SUBMIT")


def test_live_readiness_remains_false_even_if_future_gates_pass(r1i_repo):
    _, paths, _ = r1i_repo; state = i.read_json(paths.soak_state); state.update({"successful_soak_days": 20, "consecutive_healthy_days": 10}); i.atomic_json(paths.soak_state, state)
    gate = i.live_readiness(paths, power_safe_for_background_trading=True, startup_task_installed=True, broker_fractional_api_confirmed=True, strategy_performance_gate_passed=True)
    assert gate["live_ready"] is False and gate["live_available"] is False


def test_real_trading_environment_always_rejected():
    with pytest.raises(i.R1IError, match="REAL_TRADING"):
        i.reject_real_environment("TrdEnv.REAL")


def test_eod_reconciliation_has_zero_open_and_pending(r1i_repo):
    _, paths, _ = r1i_repo; rec = i.end_of_day_reconciliation(paths, et(16, 0))
    assert rec["open_order_count"] == 0 and rec["pending_fill_count"] == 0 and rec["unreconciled_difference"] == "0"


def test_all_required_outputs_generated(r1i_repo):
    repo, paths, _ = r1i_repo; i.write_summary(repo)
    for name in ("r1i_summary.json", "paper_soak_state.json", "paper_soak_daily_history.csv", "paper_eod_reconciliation.json", "replay_scenario_results.csv", "fault_injection_results.csv", "intent_idempotency_report.json", "broker_event_dedup_report.json", "deal_event_dedup_report.json", "live_readiness_gate.json", "validation_report.md"):
        assert (paths.output / name).exists(), name


def test_dashboard_exposes_soak_and_live_gate_metrics():
    text = (HERE / "v22_047_r1e_windows_service_hardening.py").read_text(encoding="utf-8")
    for label in ("PAPER SOAK STATUS", "CURRENT SOAK DAY", "SUCCESSFUL SOAK DAYS", "FAILED SOAK DAYS", "CONSECUTIVE HEALTHY DAYS", "LAST 09:45 DECISION", "LAST PAPER ORDER", "LAST RECONCILIATION", "DUPLICATE ORDER COUNT", "PROTECTED ASSET ACTION COUNT", "REAL API CALL COUNT", "QQQ DAILY RETURN", "PAPER DAILY RETURN", "PAPER EXCESS RETURN"):
        assert label in text
    assert "v22_047_r1i_paper_soak_replay_fault_injection_and_live_readiness_gate.py" in text
