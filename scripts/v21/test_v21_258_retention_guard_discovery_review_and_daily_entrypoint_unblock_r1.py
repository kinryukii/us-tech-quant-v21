from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import re
from pathlib import Path

P = Path(__file__).with_name("v21_258_retention_guard_discovery_review_and_daily_entrypoint_unblock_r1.py")
S = importlib.util.spec_from_file_location("m258", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or (list(rows[0].keys()) if rows else ["path", "relative_path", "classification", "selected_for_patch", "notes"])
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def seed(tmp_path: Path, missing257: bool = False, missing256: bool = False, candidates: str = "absent", history: bool = False):
    repo = tmp_path / "repo"
    if not missing257:
        write_json(repo / m.V257_REL / "v21_257_summary.json", {"entrypoint_recommendation": "ACCEPTED_WITH_RETENTION_REVIEW_REQUIRED", "execute_passed": True, "mandatory_child_stages_succeeded": True, "combined_report_created": True, "retention_guard_readiness_label": "RETENTION_GUARD_DISCOVERY_REVIEW_REQUIRED", "retention_review_required": True, "accepted_with_retention_review_required": True})
    if not missing256:
        write_json(repo / m.V256_REL / "v21_256_summary.json", {"run_mode": "Execute", "child_stage_succeeded_count": 3, "daily_chain_stage_succeeded": True, "context_block_stage_succeeded": True, "context_append_stage_succeeded": True, "latest_daily_chain_final_status": "PASS_V21_241_DAILY_CHAIN_RETENTION_GUARD_DISCOVERY_READY", "latest_daily_chain_final_decision": "DAILY_CHAIN_RETENTION_GUARD_DISCOVERY_READY_REVIEW_CANDIDATES", "retention_guard_status_found": False})
        if history:
            write_json(repo / m.V256_REL / "v21_256_summary_auditonly.json", {"run_mode": "AuditOnly"})
            write_json(repo / m.V256_REL / "v21_256_summary_execute.json", {"run_mode": "Execute"})
    write_json(repo / m.V241_REL / "v21_241_summary.json", {"final_status": "PASS_V21_241_DAILY_CHAIN_RETENTION_GUARD_DISCOVERY_READY", "final_decision": "DAILY_CHAIN_RETENTION_GUARD_DISCOVERY_READY_REVIEW_CANDIDATES"})
    if candidates == "observation":
        write_csv(repo / m.V241_REL / "v21_241_discovered_daily_chain_candidates.csv", [{"path": "x", "relative_path": "scripts/v21/run_daily.ps1", "classification": "CURRENT_DAILY_CHAIN_CONFIRMED", "selected_for_patch": "False", "notes": ""}])
    elif candidates == "future":
        write_csv(repo / m.V241_REL / "v21_241_discovered_daily_chain_candidates.csv", [{"path": "x", "relative_path": "scripts/v21/old_test.ps1", "classification": "LEGACY_OR_STAGE_CHAIN", "selected_for_patch": "False", "notes": ""}])
    elif candidates == "blocking":
        write_csv(repo / m.V241_REL / "v21_241_discovered_daily_chain_candidates.csv", [{"path": "x", "relative_path": "bad", "classification": "HARD_BUDGET_BLOCKER", "selected_for_patch": "False", "notes": "block"}])
    else:
        write_csv(repo / m.V241_REL / "v21_241_discovered_daily_chain_candidates.csv", [])
    write_csv(repo / m.V241_REL / "v21_241_skipped_blockers.csv", [], ["blocker_type", "path", "notes"])
    protected = repo / "protected.txt"
    protected.write_text("protected", encoding="utf-8")
    before = hashlib.sha256(protected.read_bytes()).hexdigest()
    return repo, protected, before


def test_missing_v21_257_summary(tmp_path):
    repo, _, _ = seed(tmp_path, missing257=True)
    s = m.run(repo)
    assert s["final_status"] == "FAIL_V21_258_RETENTION_REVIEW_INPUT_MISSING"


def test_missing_v21_256_summary(tmp_path):
    repo, _, _ = seed(tmp_path, missing256=True)
    s = m.run(repo)
    assert s["final_status"] == "FAIL_V21_258_RETENTION_REVIEW_INPUT_MISSING"


def test_execute_pass_with_retention_review_required(tmp_path):
    repo, _, _ = seed(tmp_path, candidates="absent")
    s = m.run(repo)
    assert s["execute_passed"] is True
    assert s["retention_guard_readiness_label_before"] == "RETENTION_GUARD_DISCOVERY_REVIEW_REQUIRED"


def test_candidates_absent_discovery_status_unblocks_with_history_warning(tmp_path):
    repo, _, _ = seed(tmp_path, candidates="absent")
    s = m.run(repo)
    assert s["retention_review_resolved"] is True
    assert s["final_status"] == "WARN_V21_258_RETENTION_REVIEW_READY_WITH_RUNMODE_HISTORY_WARNING"


def test_observation_only_candidates(tmp_path):
    repo, _, _ = seed(tmp_path, candidates="observation", history=True)
    s = m.run(repo)
    assert s["final_status"] == "PARTIAL_PASS_V21_258_DAILY_ENTRYPOINT_ACCEPTED_WITH_RETENTION_OBSERVATION"
    assert s["accepted_with_retention_observation"] is True


def test_future_cleanup_only_candidates(tmp_path):
    repo, _, _ = seed(tmp_path, candidates="future", history=True)
    s = m.run(repo)
    assert s["future_cleanup_only_candidate_count"] == 1
    assert s["blocking_retention_candidate_count"] == 0


def test_blocking_candidate_prevents_unblock(tmp_path):
    repo, _, _ = seed(tmp_path, candidates="blocking", history=True)
    s = m.run(repo)
    assert s["final_status"] == "FAIL_V21_258_DAILY_ENTRYPOINT_STILL_BLOCKED_BY_RETENTION"


def test_unblock_recommendation_generation(tmp_path):
    repo, _, _ = seed(tmp_path, candidates="absent", history=True)
    s = m.run(repo)
    data = rows(repo / m.OUT_REL / "daily_entrypoint_unblock_recommendation.csv")
    assert s["entrypoint_unblock_recommendation"] == "DAILY_ENTRYPOINT_UNBLOCKED_AFTER_RETENTION_REVIEW"
    assert data[0]["entrypoint_unblock_recommendation"] == "DAILY_ENTRYPOINT_UNBLOCKED_AFTER_RETENTION_REVIEW"


def test_run_mode_history_not_persisted_warning(tmp_path):
    repo, _, _ = seed(tmp_path, candidates="absent", history=False)
    s = m.run(repo)
    assert s["run_mode_history_label"] == "RUN_MODE_HISTORY_NOT_PERSISTED"
    assert s["run_mode_history_warning"] is True


def test_no_go_gates(tmp_path):
    repo, _, _ = seed(tmp_path, history=True)
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
    repo, _, _ = seed(tmp_path, history=True)
    m.run(repo)
    payload = json.loads((repo / m.OUT_REL / "v21_258_summary.json").read_text(encoding="utf-8"))
    for k in ["final_status", "final_decision", "entrypoint_unblock_recommendation", "v21_257_entrypoint_recommendation", "execute_passed", "mandatory_child_stages_succeeded", "combined_report_created", "retention_guard_readiness_label_before", "retention_guard_readiness_label_after", "retention_review_required_before", "retention_review_resolved", "retention_candidate_count", "blocking_retention_candidate_count", "observation_only_retention_candidate_count", "future_cleanup_only_candidate_count", "run_mode_history_label", "run_mode_history_warning", "accepted_daily_research_entrypoint_after_review", "accepted_with_retention_observation", "research_only", "retention_review_only", "retention_delete_allowed", "retention_move_allowed", "official_adoption_allowed", "broker_action_allowed", "factor_promotion_allowed", "weight_update_allowed", "ranking_mutation_allowed", "trade_plan_mutation_allowed", "child_output_mutation_allowed", "automatic_ticker_replacement_allowed", "automatic_position_increase_allowed", "automatic_trade_trigger_allowed", "protected_outputs_modified", "market_data_fetch_allowed", "missing_input_count", "warning_count", "error_count"]:
        assert k in payload


def test_required_output_files(tmp_path):
    repo, _, _ = seed(tmp_path, history=True)
    m.run(repo)
    for name in ["retention_guard_discovery_review_audit.csv", "retention_candidate_entrypoint_impact_review.csv", "daily_entrypoint_unblock_recommendation.csv", "run_mode_history_audit.csv", "retention_review_no_mutation_audit.csv", "daily_entrypoint_gate_audit.csv", "V21.258_retention_guard_discovery_review_and_daily_entrypoint_unblock_report.txt"]:
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
