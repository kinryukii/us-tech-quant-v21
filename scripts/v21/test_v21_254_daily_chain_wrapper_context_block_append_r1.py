from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import re
from pathlib import Path

P = Path(__file__).with_name("v21_254_daily_chain_wrapper_context_block_append_r1.py")
S = importlib.util.spec_from_file_location("m254", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def seed(tmp_path: Path, missing253_summary: bool = False, missing253_report: bool = False, missing_chain: bool = False):
    repo = tmp_path / "repo"
    r253 = repo / m.V253_REL
    if not missing253_summary:
        write_json(r253 / "v21_253_summary.json", {"context_section_count": 6, "final_status": "PASS", "broker_action_allowed": False})
    if not missing253_report:
        r253.mkdir(parents=True, exist_ok=True)
        (r253 / "daily_research_context_block_for_report.txt").write_text(
            "V21.253 Daily Research Context Block\n"
            "[DRAM_PRIMARY_FOCUS_STATUS]\n- dram_primary_focus_active: True\n"
            "[LATEST_DRAM_CHAIN_STATUS]\n- latest_dram_final_status: PASS\n"
            "[STRATEGY_GOVERNANCE_CONTEXT]\n- current_regime_shadow_primary: E_R3\n"
            "[TECHNICAL_FREEZE_STATUS]\n- technical_checklist_observation_only: True\n"
            "[RETENTION_AND_CACHE_GUARD_STATUS]\n- retention_guard_status_found: True\n"
            "[BROKER_AND_ACTION_GATE_STATUS]\n- broker_action_allowed: False\n",
            encoding="utf-8",
        )
    child = repo / "outputs/v21/V21.241_DAILY_CHAIN_RETENTION_GUARD_INTEGRATION/v21_241_summary.json"
    if not missing_chain:
        write_json(child, {"final_status": "PASS_V21_241_DAILY_CHAIN_RETENTION_GUARD_READY", "final_decision": "DAILY_CHAIN_RETENTION_GUARD_READY_FOR_USE"})
    protected = repo / "protected.txt"
    protected.write_text("protected", encoding="utf-8")
    child_hash = hashlib.sha256(child.read_bytes()).hexdigest() if child.exists() else ""
    protected_hash = hashlib.sha256(protected.read_bytes()).hexdigest()
    return repo, child, child_hash, protected, protected_hash


def test_missing_v21_253_summary(tmp_path):
    repo, *_ = seed(tmp_path, missing253_summary=True)
    s = m.run(repo)
    assert s["final_status"] == "FAIL_V21_254_DAILY_CHAIN_CONTEXT_APPEND_INPUT_MISSING"
    assert s["missing_input_count"] == 1


def test_missing_v21_253_report_block(tmp_path):
    repo, *_ = seed(tmp_path, missing253_report=True)
    s = m.run(repo)
    assert s["final_status"] == "FAIL_V21_254_DAILY_CHAIN_CONTEXT_APPEND_INPUT_MISSING"
    assert s["missing_input_count"] == 1


def test_missing_latest_daily_chain_summary_warns(tmp_path):
    repo, *_ = seed(tmp_path, missing_chain=True)
    s = m.run(repo)
    assert s["final_status"] == "WARN_V21_254_DAILY_CHAIN_CONTEXT_APPEND_READY_WITH_MISSING_DAILY_CHAIN"
    assert s["latest_daily_chain_summary_found"] is False
    assert s["error_count"] == 0


def test_latest_daily_chain_discovery(tmp_path):
    repo, *_ = seed(tmp_path)
    s = m.run(repo)
    assert s["latest_daily_chain_summary_found"] is True
    data = rows(repo / m.OUT_REL / "latest_daily_chain_discovery_audit.csv")
    assert any(r["selected"] == "True" for r in data)


def test_context_block_append_into_combined_report(tmp_path):
    repo, *_ = seed(tmp_path)
    m.run(repo)
    text = (repo / m.OUT_REL / "daily_chain_combined_context_report.txt").read_text(encoding="utf-8")
    assert "Latest Daily Chain / Retention Guard Summary" in text
    assert "Appended V21.253 Daily Research Context Block" in text
    assert "DRAM_PRIMARY_FOCUS_STATUS" in text


def test_combined_summary_csv_generation(tmp_path):
    repo, *_ = seed(tmp_path)
    m.run(repo)
    data = rows(repo / m.OUT_REL / "daily_chain_combined_context_summary.csv")
    assert any(r["summary_key"] == "combined_report_created" and r["summary_value"] == "True" for r in data)


def test_append_audit_generation(tmp_path):
    repo, *_ = seed(tmp_path)
    m.run(repo)
    data = rows(repo / m.OUT_REL / "daily_chain_context_append_audit.csv")
    assert data
    assert {r["passed"] for r in data} == {"True"}


def test_wrapper_integration_recommendation_generation(tmp_path):
    repo, *_ = seed(tmp_path)
    m.run(repo)
    data = rows(repo / m.OUT_REL / "daily_chain_wrapper_integration_recommendation.csv")
    assert any(r["recommendation"] == "CALL_AFTER_V21_241_RETENTION_GUARD" for r in data)
    assert any(r["recommendation"] == "DO_NOT_USE_AS_RANKING_STEP" for r in data)


def test_append_only_and_action_gates(tmp_path):
    repo, *_ = seed(tmp_path)
    s = m.run(repo)
    assert s["append_only"] is True
    assert s["child_output_mutation_allowed"] is False
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["ranking_mutation_allowed"] is False
    assert s["weight_update_allowed"] is False
    assert s["trade_plan_mutation_allowed"] is False
    assert s["automatic_ticker_replacement_allowed"] is False
    assert s["automatic_position_increase_allowed"] is False
    assert s["automatic_trade_trigger_allowed"] is False


def test_summary_json_schema(tmp_path):
    repo, *_ = seed(tmp_path)
    m.run(repo)
    payload = json.loads((repo / m.OUT_REL / "v21_254_summary.json").read_text(encoding="utf-8"))
    for k in [
        "final_status",
        "final_decision",
        "latest_daily_chain_summary_found",
        "latest_daily_chain_final_status",
        "latest_daily_chain_final_decision",
        "v21_253_context_block_found",
        "context_section_count",
        "combined_report_created",
        "append_only",
        "research_only",
        "official_adoption_allowed",
        "broker_action_allowed",
        "factor_promotion_allowed",
        "weight_update_allowed",
        "ranking_mutation_allowed",
        "trade_plan_mutation_allowed",
        "child_output_mutation_allowed",
        "automatic_ticker_replacement_allowed",
        "automatic_position_increase_allowed",
        "automatic_trade_trigger_allowed",
        "protected_outputs_modified",
        "market_data_fetch_allowed",
        "missing_input_count",
        "warning_count",
        "error_count",
    ]:
        assert k in payload


def test_gate_status_append_audit(tmp_path):
    repo, *_ = seed(tmp_path)
    m.run(repo)
    data = rows(repo / m.OUT_REL / "gate_status_append_audit.csv")
    assert data
    assert {r["passed"] for r in data} == {"True"}


def test_no_market_data_provider_call_static(tmp_path):
    repo, *_ = seed(tmp_path)
    s = m.run(repo)
    assert s["market_data_fetch_allowed"] is False
    text = P.read_text(encoding="utf-8").lower()
    banned = [
        r"\bimport\s+yfinance\b",
        r"\bfrom\s+yfinance\b",
        r"\bimport\s+moomoo\b",
        r"\bfrom\s+moomoo\b",
        r"\bimport\s+futu\b",
        r"\bfrom\s+futu\b",
        r"\brequests\.",
        r"\burllib\.",
    ]
    assert not any(re.search(p, text) for p in banned)


def test_no_child_output_or_protected_output_mutation(tmp_path):
    repo, child, child_hash, protected, protected_hash = seed(tmp_path)
    m.run(repo)
    assert hashlib.sha256(child.read_bytes()).hexdigest() == child_hash
    assert hashlib.sha256(protected.read_bytes()).hexdigest() == protected_hash
