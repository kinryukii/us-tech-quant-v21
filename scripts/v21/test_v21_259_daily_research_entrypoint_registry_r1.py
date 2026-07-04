from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import re
from pathlib import Path

P = Path(__file__).with_name("v21_259_daily_research_entrypoint_registry_r1.py")
S = importlib.util.spec_from_file_location("m259", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def seed(tmp_path: Path, missing258: bool = False, missing257: bool = False, missing256: bool = False, mode: str = "observation", history_warning: bool = False):
    repo = tmp_path / "repo"
    if not missing258:
        if mode == "full":
            v258 = {"accepted_daily_research_entrypoint_after_review": True, "accepted_with_retention_observation": False, "blocking_retention_candidate_count": 0, "run_mode_history_label": "RUN_MODE_HISTORY_PERSISTED", "run_mode_history_warning": history_warning}
        elif mode == "blocked":
            v258 = {"accepted_daily_research_entrypoint_after_review": False, "accepted_with_retention_observation": False, "blocking_retention_candidate_count": 2, "run_mode_history_label": "RUN_MODE_HISTORY_PERSISTED", "run_mode_history_warning": history_warning}
        else:
            v258 = {"accepted_daily_research_entrypoint_after_review": False, "accepted_with_retention_observation": True, "blocking_retention_candidate_count": 0, "run_mode_history_label": "RUN_MODE_HISTORY_NOT_PERSISTED", "run_mode_history_warning": True if history_warning else False}
        write_json(repo / m.V258_REL / "v21_258_summary.json", v258)
    if not missing257:
        write_json(repo / m.V257_REL / "v21_257_summary.json", {"entrypoint_recommendation": "ACCEPTED_WITH_RETENTION_REVIEW_REQUIRED", "execute_passed": True, "mandatory_child_stages_succeeded": True, "combined_report_created": True, "retention_review_required": True, "accepted_with_retention_review_required": True})
    if not missing256:
        write_json(repo / m.V256_REL / "v21_256_summary.json", {"final_status": "PASS_V21_256_DAILY_MASTER_WRAPPER_READY", "final_decision": "READY", "run_mode": "Execute", "child_stage_count": 3, "child_stage_succeeded_count": 3, "daily_chain_stage_succeeded": True, "context_block_stage_succeeded": True, "context_append_stage_succeeded": True, "combined_report_created": True})
    protected = repo / "protected.txt"
    protected.write_text("protected", encoding="utf-8")
    before = hashlib.sha256(protected.read_bytes()).hexdigest()
    return repo, protected, before


def test_missing_v21_258_summary(tmp_path):
    repo, _, _ = seed(tmp_path, missing258=True)
    assert m.run(repo)["final_status"] == "FAIL_V21_259_ENTRYPOINT_REGISTRY_INPUT_MISSING"


def test_missing_v21_257_summary(tmp_path):
    repo, _, _ = seed(tmp_path, missing257=True)
    assert m.run(repo)["final_status"] == "FAIL_V21_259_ENTRYPOINT_REGISTRY_INPUT_MISSING"


def test_missing_v21_256_summary(tmp_path):
    repo, _, _ = seed(tmp_path, missing256=True)
    assert m.run(repo)["final_status"] == "FAIL_V21_259_ENTRYPOINT_REGISTRY_INPUT_MISSING"


def test_full_accepted_entrypoint_registration(tmp_path):
    repo, _, _ = seed(tmp_path, mode="full")
    s = m.run(repo)
    assert s["final_status"] == "PASS_V21_259_DAILY_RESEARCH_ENTRYPOINT_REGISTERED"
    data = rows(repo / m.OUT_REL / "daily_research_entrypoint_registry.csv")
    assert data[0]["entrypoint_status"] == "ACCEPTED"


def test_retention_observation_registration(tmp_path):
    repo, _, _ = seed(tmp_path, mode="observation")
    s = m.run(repo)
    assert s["final_status"] == "PARTIAL_PASS_V21_259_ENTRYPOINT_REGISTERED_WITH_RETENTION_OBSERVATION"
    assert s["entrypoint_status"] == "ACCEPTED_WITH_RETENTION_OBSERVATION"


def test_blocking_retention_candidate_prevents_registry(tmp_path):
    repo, _, _ = seed(tmp_path, mode="blocked")
    s = m.run(repo)
    assert s["final_status"] == "FAIL_V21_259_ENTRYPOINT_REGISTRY_BLOCKED_BY_RETENTION"


def test_run_instruction_card_generation(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    text = (repo / m.OUT_REL / "daily_research_entrypoint_run_instruction_card.txt").read_text(encoding="utf-8")
    assert "Primary command" in text
    assert "-Execute" in text
    assert "Must not do" in text


def test_registry_maintenance_policy_generation(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    data = rows(repo / m.OUT_REL / "daily_research_entrypoint_registry_maintenance_policy.csv")
    assert any(r["policy_name"] == "REVIEW_IF_V21_256_EXECUTE_FAILS" for r in data)
    assert any(r["policy_name"] == "REVIEW_IF_DRAM_PRIMARY_FOCUS_CHANGES" for r in data)


def test_run_mode_history_warning_propagation(tmp_path):
    repo, _, _ = seed(tmp_path, history_warning=True)
    s = m.run(repo)
    assert s["run_mode_history_warning"] is True
    assert s["warning_count"] >= 1


def test_no_go_gates(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    assert s["retention_delete_allowed"] is False
    assert s["retention_move_allowed"] is False
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
    payload = json.loads((repo / m.OUT_REL / "v21_259_summary.json").read_text(encoding="utf-8"))
    for k in ["final_status", "final_decision", "accepted_entrypoint_name", "accepted_entrypoint_script", "recommended_command", "entrypoint_status", "accepted_with_retention_observation", "retention_observation_required", "blocking_retention_candidate_count", "run_mode_history_label", "run_mode_history_warning", "registry_created", "run_instruction_card_created", "registry_maintenance_policy_created", "research_only", "registry_only", "retention_delete_allowed", "retention_move_allowed", "official_adoption_allowed", "broker_action_allowed", "factor_promotion_allowed", "weight_update_allowed", "ranking_mutation_allowed", "trade_plan_mutation_allowed", "child_output_mutation_allowed", "automatic_ticker_replacement_allowed", "automatic_position_increase_allowed", "automatic_trade_trigger_allowed", "protected_outputs_modified", "market_data_fetch_allowed", "missing_input_count", "warning_count", "error_count"]:
        assert k in payload


def test_required_output_files(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    for name in ["daily_research_entrypoint_registry.csv", "daily_research_entrypoint_run_instruction_card.txt", "daily_research_entrypoint_registry_no_go_audit.csv", "daily_research_entrypoint_registry_maintenance_policy.csv", "daily_research_entrypoint_gate_audit.csv", "V21.259_daily_research_entrypoint_registry_report.txt"]:
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
