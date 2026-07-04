from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import re
from pathlib import Path

P = Path(__file__).with_name("v21_257_daily_master_wrapper_adoption_readiness_audit_r1.py")
S = importlib.util.spec_from_file_location("m257", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def v256(mode: str = "Execute", status: str = "PASS_V21_256_DAILY_MASTER_WRAPPER_READY", combined: bool = True, child_ok: bool = True, retention_found: bool = True):
    return {
        "final_status": status,
        "final_decision": "READY",
        "run_mode": mode,
        "child_stage_count": 3,
        "child_stage_succeeded_count": 3 if child_ok else 2,
        "daily_chain_stage_succeeded": child_ok,
        "context_block_stage_succeeded": child_ok,
        "context_append_stage_succeeded": child_ok,
        "latest_daily_chain_final_status": "PASS_V21_241_DAILY_CHAIN_RETENTION_GUARD_READY",
        "latest_daily_chain_final_decision": "DAILY_CHAIN_RETENTION_GUARD_READY_FOR_USE",
        "latest_context_block_final_status": "PASS_V21_253",
        "latest_context_append_final_status": "PASS_V21_254",
        "retention_guard_status_found": retention_found,
        "combined_report_created": combined,
        "dram_primary_focus_active": True,
        "technical_freeze_enforced": True,
        "strategy_governance_research_context_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
    }


def seed(tmp_path: Path, execute: bool = True, child_fail: bool = False, combined: bool = True, retention: str = "ready", missing_v256: bool = False):
    repo = tmp_path / "repo"
    if not missing_v256:
        write_json(repo / m.V256_REL / "v21_256_summary_auditonly.json", v256("AuditOnly"))
        if execute:
            write_json(repo / m.V256_REL / "v21_256_summary_execute.json", v256("Execute", status="FAIL_V21_256_DAILY_MASTER_WRAPPER_CHILD_FAILURE" if child_fail else "PASS_V21_256_DAILY_MASTER_WRAPPER_READY", combined=combined, child_ok=not child_fail, retention_found=retention == "ready"))
        write_json(repo / m.V256_REL / "v21_256_summary.json", v256("Execute" if execute else "AuditOnly", combined=combined, child_ok=not child_fail, retention_found=retention == "ready"))
    if retention == "ready":
        write_json(repo / m.V241_REL / "v21_241_summary.json", {"final_status": "PASS_V21_241_DAILY_CHAIN_RETENTION_GUARD_READY", "final_decision": "DAILY_CHAIN_RETENTION_GUARD_READY_FOR_USE"})
    elif retention == "review":
        write_json(repo / m.V241_REL / "v21_241_summary.json", {"final_status": "PASS_V21_241_DAILY_CHAIN_RETENTION_GUARD_DISCOVERY_READY", "final_decision": "REVIEW_CANDIDATES"})
    write_json(repo / m.V253_REL / "v21_253_summary.json", {"final_status": "PASS", "dram_primary_focus_active": True, "technical_freeze_enforced": True, "strategy_governance_research_context_only": True})
    write_json(repo / m.V254_REL / "v21_254_summary.json", {"final_status": "PASS", "combined_report_created": combined})
    protected = repo / "protected.txt"
    protected.write_text("protected", encoding="utf-8")
    before = hashlib.sha256(protected.read_bytes()).hexdigest()
    return repo, protected, before


def test_missing_v21_256_summary(tmp_path):
    repo, _, _ = seed(tmp_path, missing_v256=True)
    s = m.run(repo)
    assert s["final_status"] == "FAIL_V21_257_DAILY_MASTER_ENTRYPOINT_INPUT_MISSING"


def test_auditonly_only_warning(tmp_path):
    repo, _, _ = seed(tmp_path, execute=False)
    s = m.run(repo)
    assert s["final_status"] == "WARN_V21_257_DAILY_MASTER_ENTRYPOINT_AUDIT_ONLY_ONLY"


def test_execute_pass_retention_ready_accepted(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    assert s["final_status"] == "PASS_V21_257_DAILY_MASTER_ENTRYPOINT_ACCEPTED_RESEARCH_ONLY"
    assert s["entrypoint_recommendation"] == "ACCEPTED_DAILY_RESEARCH_ENTRYPOINT"


def test_execute_pass_retention_review_accepted_partial(tmp_path):
    repo, _, _ = seed(tmp_path, retention="review")
    s = m.run(repo)
    assert s["final_status"] == "PARTIAL_PASS_V21_257_DAILY_MASTER_ENTRYPOINT_ACCEPTED_WITH_RETENTION_REVIEW"
    assert s["entrypoint_recommendation"] == "ACCEPTED_WITH_RETENTION_REVIEW_REQUIRED"


def test_execute_child_failure_fails(tmp_path):
    repo, _, _ = seed(tmp_path, child_fail=True)
    s = m.run(repo)
    assert s["final_status"] == "FAIL_V21_257_DAILY_MASTER_ENTRYPOINT_CHILD_FAILURE"


def test_missing_combined_report_prevents_acceptance(tmp_path):
    repo, _, _ = seed(tmp_path, combined=False)
    s = m.run(repo)
    assert s["final_status"] == "FAIL_V21_257_DAILY_MASTER_ENTRYPOINT_CHILD_FAILURE"


def test_retention_guard_readiness_labels(tmp_path):
    repo, _, _ = seed(tmp_path, retention="review")
    m.run(repo)
    data = rows(repo / m.OUT_REL / "retention_guard_readiness_audit.csv")
    assert data[0]["retention_guard_readiness_label"] == "RETENTION_GUARD_DISCOVERY_REVIEW_REQUIRED"


def test_gate_audit_and_no_go_gates(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    data = rows(repo / m.OUT_REL / "daily_master_wrapper_gate_audit.csv")
    assert {r["passed"] for r in data} == {"True"}
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
    payload = json.loads((repo / m.OUT_REL / "v21_257_summary.json").read_text(encoding="utf-8"))
    for k in [
        "final_status", "final_decision", "entrypoint_recommendation", "auditonly_passed", "execute_passed",
        "child_stage_count", "child_stage_succeeded_count", "mandatory_child_stages_succeeded",
        "combined_report_created", "retention_guard_readiness_label", "retention_review_required",
        "dram_primary_focus_active", "technical_freeze_enforced", "strategy_governance_research_context_only",
        "accepted_daily_research_entrypoint", "accepted_with_retention_review_required", "research_only",
        "official_adoption_allowed", "broker_action_allowed", "factor_promotion_allowed", "weight_update_allowed",
        "ranking_mutation_allowed", "trade_plan_mutation_allowed", "child_output_mutation_allowed",
        "automatic_ticker_replacement_allowed", "automatic_position_increase_allowed", "automatic_trade_trigger_allowed",
        "protected_outputs_modified", "market_data_fetch_allowed", "missing_input_count", "warning_count", "error_count",
    ]:
        assert k in payload


def test_required_output_files(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    for name in [
        "daily_master_wrapper_adoption_readiness_audit.csv",
        "daily_master_wrapper_entrypoint_recommendation.csv",
        "retention_guard_readiness_audit.csv",
        "daily_master_wrapper_keep_watch_fix_review.csv",
        "V21.257_daily_master_wrapper_adoption_readiness_audit_report.txt",
    ]:
        assert (repo / m.OUT_REL / name).exists()


def test_no_market_data_provider_call_static(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    assert s["market_data_fetch_allowed"] is False
    text = P.read_text(encoding="utf-8").lower()
    banned = [r"\bimport\s+yfinance\b", r"\bfrom\s+yfinance\b", r"\bimport\s+moomoo\b", r"\bfrom\s+moomoo\b", r"\bimport\s+futu\b", r"\bfrom\s+futu\b", r"\brequests\."]
    assert not any(re.search(p, text) for p in banned)


def test_no_protected_output_mutation(tmp_path):
    repo, protected, before = seed(tmp_path)
    m.run(repo)
    assert hashlib.sha256(protected.read_bytes()).hexdigest() == before
