from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import re
from pathlib import Path

P = Path(__file__).with_name("v21_256_daily_chain_master_wrapper_with_context_r1.py")
S = importlib.util.spec_from_file_location("m256", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def make_wrappers(repo: Path) -> None:
    for rel in [
        "scripts/v21/run_v21_241_daily_chain_retention_guard_integration.ps1",
        "scripts/v21/run_v21_253_daily_research_chain_context_block_integration_r1.ps1",
        "scripts/v21/run_v21_254_daily_chain_wrapper_context_block_append_r1.ps1",
    ]:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# test wrapper", encoding="utf-8")


def seed(tmp_path: Path, missing_append: bool = False, child_warn: bool = False, wrappers: bool = True):
    repo = tmp_path / "repo"
    if wrappers:
        make_wrappers(repo)
    write_json(repo / m.V241_REL / "v21_241_summary.json", {"final_status": "PASS_V21_241_DAILY_CHAIN_RETENTION_GUARD_READY", "final_decision": "DAILY_CHAIN_RETENTION_GUARD_READY_FOR_USE"})
    write_json(repo / m.V253_REL / "v21_253_summary.json", {"final_status": "PASS_V21_253_DAILY_CONTEXT_BLOCK_READY_RESEARCH_ONLY", "final_decision": "READY", "dram_primary_focus_active": True, "technical_freeze_enforced": True, "strategy_governance_research_context_only": True, "retention_guard_status_found": True})
    if not missing_append:
        status = "WARN_V21_254_DAILY_CHAIN_CONTEXT_APPEND_READY_WITH_MISSING_DAILY_CHAIN" if child_warn else "PASS_V21_254_DAILY_CHAIN_CONTEXT_APPEND_READY"
        write_json(repo / m.V254_REL / "v21_254_summary.json", {"final_status": status, "final_decision": "READY", "combined_report_created": True})
    protected = repo / "protected.txt"
    protected.write_text("protected", encoding="utf-8")
    before = hashlib.sha256(protected.read_bytes()).hexdigest()
    return repo, protected, before


def fake_runner_factory(fail_stage: str | None = None):
    def runner(cmd: list[str], cwd: Path, log_path: Path):
        text = " ".join(cmd)
        if "run_v21_241" in text:
            stage = "daily"
            path = cwd / m.V241_REL / "v21_241_summary.json"
            data = {"final_status": "PASS_V21_241_DAILY_CHAIN_RETENTION_GUARD_READY", "final_decision": "DAILY_CHAIN_RETENTION_GUARD_READY_FOR_USE"}
        elif "run_v21_253" in text:
            stage = "253"
            path = cwd / m.V253_REL / "v21_253_summary.json"
            data = {"final_status": "PASS_V21_253_DAILY_CONTEXT_BLOCK_READY_RESEARCH_ONLY", "final_decision": "READY", "dram_primary_focus_active": True, "technical_freeze_enforced": True, "strategy_governance_research_context_only": True, "retention_guard_status_found": True}
        else:
            stage = "254"
            path = cwd / m.V254_REL / "v21_254_summary.json"
            data = {"final_status": "PASS_V21_254_DAILY_CHAIN_CONTEXT_APPEND_READY", "final_decision": "READY", "combined_report_created": True}
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(f"stage={stage}", encoding="utf-8")
        if fail_stage == stage:
            return 1, f"{stage} failed"
        write_json(path, data)
        return 0, ""
    return runner


def test_audit_only_all_child_outputs_present(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    assert s["run_mode"] == "AuditOnly"
    assert s["final_status"] == "PASS_V21_256_DAILY_MASTER_WRAPPER_READY"
    assert s["child_stage_succeeded_count"] == 3


def test_audit_only_missing_context_append_output(tmp_path):
    repo, _, _ = seed(tmp_path, missing_append=True)
    s = m.run(repo)
    assert s["final_status"] == "WARN_V21_256_DAILY_MASTER_WRAPPER_AUDIT_ONLY_PARTIAL"
    assert s["context_append_stage_succeeded"] is False


def test_execute_mode_child_success_path(tmp_path):
    repo, _, _ = seed(tmp_path, missing_append=True)
    s = m.run(repo, run_mode="Execute", child_runner=fake_runner_factory())
    assert s["final_status"] == "PASS_V21_256_DAILY_MASTER_WRAPPER_READY"
    assert s["child_stage_attempted_count"] == 3
    assert s["child_stage_succeeded_count"] == 3


def test_execute_mode_daily_chain_child_failure(tmp_path):
    repo, _, _ = seed(tmp_path, missing_append=True)
    s = m.run(repo, run_mode="Execute", child_runner=fake_runner_factory("daily"))
    assert s["final_status"] == "FAIL_V21_256_DAILY_MASTER_WRAPPER_CHILD_FAILURE"


def test_execute_mode_v21_253_child_failure(tmp_path):
    repo, _, _ = seed(tmp_path, missing_append=True)
    s = m.run(repo, run_mode="Execute", child_runner=fake_runner_factory("253"))
    assert s["final_status"] == "FAIL_V21_256_DAILY_MASTER_WRAPPER_CHILD_FAILURE"


def test_execute_mode_v21_254_child_failure(tmp_path):
    repo, _, _ = seed(tmp_path, missing_append=True)
    s = m.run(repo, run_mode="Execute", child_runner=fake_runner_factory("254"))
    assert s["final_status"] == "FAIL_V21_256_DAILY_MASTER_WRAPPER_CHILD_FAILURE"


def test_child_stage_execution_ledger_generation(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    data = rows(repo / m.OUT_REL / "daily_chain_master_child_stage_ledger.csv")
    assert len(data) == 3
    assert {r["stage_name"] for r in data} == {"DAILY_CHAIN_RETENTION_GUARD", "V21_253_CONTEXT_BLOCK", "V21_254_CONTEXT_APPEND"}


def test_master_summary_and_report_generation(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    assert (repo / m.OUT_REL / "daily_chain_master_summary.csv").exists()
    text = (repo / m.OUT_REL / "daily_chain_master_report.txt").read_text(encoding="utf-8")
    assert "V21.256 Daily Chain Master Wrapper With Context" in text


def test_gate_and_no_mutation_audits(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    gates = rows(repo / m.OUT_REL / "daily_chain_master_gate_audit.csv")
    nomut = rows(repo / m.OUT_REL / "daily_chain_master_no_mutation_audit.csv")
    assert {r["passed"] for r in gates} == {"True"}
    assert {r["passed"] for r in nomut} == {"True"}


def test_no_go_gates(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["ranking_mutation_allowed"] is False
    assert s["weight_update_allowed"] is False
    assert s["trade_plan_mutation_allowed"] is False
    assert s["child_output_mutation_allowed"] is False
    assert s["automatic_ticker_replacement_allowed"] is False
    assert s["automatic_position_increase_allowed"] is False
    assert s["automatic_trade_trigger_allowed"] is False


def test_summary_json_schema(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    payload = json.loads((repo / m.OUT_REL / "v21_256_summary.json").read_text(encoding="utf-8"))
    for k in [
        "final_status", "final_decision", "run_mode", "child_stage_count", "child_stage_attempted_count",
        "child_stage_succeeded_count", "daily_chain_stage_succeeded", "context_block_stage_succeeded",
        "context_append_stage_succeeded", "latest_daily_chain_final_status", "latest_daily_chain_final_decision",
        "latest_context_block_final_status", "latest_context_append_final_status", "dram_primary_focus_active",
        "technical_freeze_enforced", "strategy_governance_research_context_only", "retention_guard_status_found",
        "combined_report_created", "research_only", "official_adoption_allowed", "broker_action_allowed",
        "factor_promotion_allowed", "weight_update_allowed", "ranking_mutation_allowed", "trade_plan_mutation_allowed",
        "child_output_mutation_allowed", "automatic_ticker_replacement_allowed", "automatic_position_increase_allowed",
        "automatic_trade_trigger_allowed", "protected_outputs_modified", "market_data_fetch_allowed",
        "missing_input_count", "warning_count", "error_count",
    ]:
        assert k in payload


def test_audit_only_default_behavior(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    assert s["run_mode"] == "AuditOnly"
    assert s["child_stage_attempted_count"] == 0


def test_no_provider_call_at_wrapper_layer_static(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    assert s["market_data_fetch_allowed"] is False
    text = P.read_text(encoding="utf-8").lower()
    banned = [r"\bimport\s+yfinance\b", r"\bfrom\s+yfinance\b", r"\bimport\s+moomoo\b", r"\bfrom\s+moomoo\b", r"\bimport\s+futu\b", r"\bfrom\s+futu\b"]
    assert not any(re.search(p, text) for p in banned)


def test_no_protected_output_mutation(tmp_path):
    repo, protected, before = seed(tmp_path)
    m.run(repo)
    assert hashlib.sha256(protected.read_bytes()).hexdigest() == before
