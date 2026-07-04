from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import re
from pathlib import Path

P = Path(__file__).with_name("v21_253_daily_research_chain_context_block_integration_r1.py")
S = importlib.util.spec_from_file_location("m253", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def seed(tmp_path: Path, missing252: bool = False, missing251: bool = False, missing250: bool = False, missing_dram: bool = False):
    repo = tmp_path / "repo"
    if not missing252:
        write_json(
            repo / m.V252_REL / "v21_252_summary.json",
            {
                "dram_primary_focus_active": True,
                "strategy_governance_research_context_only": True,
                "strategy_governance_risk_review_only": True,
                "technical_checklist_observation_only": True,
                "broker_action_allowed": False,
                "official_adoption_allowed": False,
            },
        )
    if not missing251:
        write_json(
            repo / m.V251_REL / "v21_251_summary.json",
            {
                "current_regime_shadow_primary": "E_R3_QUALITY_RISK_REPAIR_BASE",
                "long_history_fallback": "E_R2_CONSERVATIVE_DEFENSIVE_RETURN",
                "high_return_watch_only": "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL",
                "switch_condition_count": 4,
            },
        )
    if not missing250:
        write_json(
            repo / m.V250_REL / "v21_250_summary.json",
            {
                "model_entry_allowed": False,
                "technical_timing_overlay_allowed": False,
                "technical_context_filter_allowed": False,
                "technical_manual_checklist_allowed": True,
            },
        )
    if not missing_dram:
        write_json(
            repo / "outputs/v21/V21.241_DAILY_CHAIN_RETENTION_GUARD_INTEGRATION/v21_241_summary.json",
            {
                "final_status": "PASS_V21_241_DAILY_CHAIN_RETENTION_GUARD_READY",
                "final_decision": "DAILY_CHAIN_RETENTION_GUARD_READY_FOR_USE",
                "latest_dram_plan_currentness": "CURRENT",
            },
        )
    protected = repo / "protected.txt"
    protected.write_text("protected", encoding="utf-8")
    before = hashlib.sha256(protected.read_bytes()).hexdigest()
    return repo, protected, before


def context_by_section(repo: Path) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {}
    for row in rows(repo / m.OUT_REL / "daily_research_context_block.csv"):
        out.setdefault(row["section"], []).append(row)
    return out


def test_missing_v21_252_summary(tmp_path):
    repo, _, _ = seed(tmp_path, missing252=True)
    s = m.run(repo)
    assert s["final_status"] == "FAIL_V21_253_DAILY_CONTEXT_BLOCK_INPUT_MISSING"
    assert s["missing_input_count"] == 1


def test_missing_v21_251_summary(tmp_path):
    repo, _, _ = seed(tmp_path, missing251=True)
    s = m.run(repo)
    assert s["final_status"] == "FAIL_V21_253_DAILY_CONTEXT_BLOCK_INPUT_MISSING"
    assert s["missing_input_count"] == 1


def test_missing_v21_250_summary(tmp_path):
    repo, _, _ = seed(tmp_path, missing250=True)
    s = m.run(repo)
    assert s["final_status"] == "FAIL_V21_253_DAILY_CONTEXT_BLOCK_INPUT_MISSING"
    assert s["missing_input_count"] == 1


def test_missing_dram_summary_warns(tmp_path):
    repo, _, _ = seed(tmp_path, missing_dram=True)
    s = m.run(repo)
    assert s["final_status"] == "WARN_V21_253_DAILY_CONTEXT_BLOCK_READY_WITH_MISSING_DRAM_SUMMARY"
    assert s["latest_dram_summary_found"] is False
    assert s["error_count"] == 0


def test_dram_primary_focus_section_generation(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    sections = context_by_section(repo)
    assert s["dram_primary_focus_active"] is True
    assert "DRAM_PRIMARY_FOCUS_STATUS" in sections


def test_strategy_governance_context_section_generation(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    sections = context_by_section(repo)
    assert "STRATEGY_GOVERNANCE_CONTEXT" in sections
    assert any(r["context_key"] == "current_regime_shadow_primary" for r in sections["STRATEGY_GOVERNANCE_CONTEXT"])


def test_technical_freeze_section_generation(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    sections = context_by_section(repo)
    assert s["technical_freeze_enforced"] is True
    assert "TECHNICAL_FREEZE_STATUS" in sections


def test_retention_cache_guard_section_generation(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    sections = context_by_section(repo)
    assert s["retention_guard_status_found"] is True
    assert "RETENTION_AND_CACHE_GUARD_STATUS" in sections


def test_broker_action_gate_section_generation(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    sections = context_by_section(repo)
    assert "BROKER_AND_ACTION_GATE_STATUS" in sections
    assert any(r["blocked_use"] == "BROKER_ACTION" for r in sections["BROKER_AND_ACTION_GATE_STATUS"])


def test_report_text_block_generation(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    text = (repo / m.OUT_REL / "daily_research_context_block_for_report.txt").read_text(encoding="utf-8")
    assert "V21.253 Daily Research Context Block" in text
    assert "DRAM_PRIMARY_FOCUS_STATUS" in text
    assert "No official adoption" in text


def test_daily_chain_integration_recommendation_generation(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    data = rows(repo / m.OUT_REL / "daily_chain_context_integration_recommendation.csv")
    assert any(r["recommendation"] == "APPEND_CONTEXT_BLOCK_AFTER_DAILY_RESULT_SUMMARY" for r in data)
    assert any(r["recommendation"] == "DO_NOT_FETCH_MARKET_DATA" for r in data)


def test_no_action_and_mutation_gates(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["ranking_mutation_allowed"] is False
    assert s["weight_update_allowed"] is False
    assert s["trade_plan_mutation_allowed"] is False
    assert s["automatic_ticker_replacement_allowed"] is False
    assert s["automatic_position_increase_allowed"] is False
    assert s["automatic_trade_trigger_allowed"] is False


def test_summary_json_schema(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    payload = json.loads((repo / m.OUT_REL / "v21_253_summary.json").read_text(encoding="utf-8"))
    for k in [
        "final_status",
        "final_decision",
        "context_section_count",
        "latest_dram_summary_found",
        "latest_dram_final_status",
        "latest_dram_final_decision",
        "dram_primary_focus_active",
        "strategy_governance_research_context_only",
        "strategy_governance_risk_review_only",
        "technical_checklist_observation_only",
        "technical_freeze_enforced",
        "current_regime_shadow_primary",
        "long_history_fallback",
        "high_return_watch_only",
        "retention_guard_status_found",
        "broker_action_allowed",
        "official_adoption_allowed",
        "factor_promotion_allowed",
        "weight_update_allowed",
        "ranking_mutation_allowed",
        "trade_plan_mutation_allowed",
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


def test_context_json_generation(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    payload = json.loads((repo / m.OUT_REL / "daily_research_context_block.json").read_text(encoding="utf-8"))
    assert payload["summary"]["context_section_count"] == 6
    assert payload["context"]


def test_gate_status_context_audit(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    data = rows(repo / m.OUT_REL / "gate_status_context_audit.csv")
    assert data
    assert {r["passed"] for r in data} == {"True"}


def test_no_market_data_provider_call_static(tmp_path):
    repo, _, _ = seed(tmp_path)
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


def test_no_protected_output_mutation(tmp_path):
    repo, protected, before = seed(tmp_path)
    m.run(repo)
    assert hashlib.sha256(protected.read_bytes()).hexdigest() == before
