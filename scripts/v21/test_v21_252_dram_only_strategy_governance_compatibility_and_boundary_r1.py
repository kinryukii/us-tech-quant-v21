from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import re
from pathlib import Path

P = Path(__file__).with_name("v21_252_dram_only_strategy_governance_compatibility_and_boundary_r1.py")
S = importlib.util.spec_from_file_location("m252", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def seed(tmp_path: Path, missing251: bool = False, missing250: bool = False, missing_dram: bool = False, technical_violation: bool = False):
    repo = tmp_path / "repo"
    if not missing251:
        write_json(
            repo / m.V251_REL / "v21_251_summary.json",
            {
                "current_regime_shadow_primary": "E_R3_QUALITY_RISK_REPAIR_BASE",
                "long_history_fallback": "E_R2_CONSERVATIVE_DEFENSIVE_RETURN",
                "high_return_watch_only": "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL",
                "switch_condition_count": 4,
                "dram_compatible": True,
                "official_adoption_allowed": False,
                "broker_action_allowed": False,
            },
        )
    if not missing250:
        write_json(
            repo / m.V250_REL / "v21_250_summary.json",
            {
                "model_entry_allowed": False,
                "technical_timing_overlay_allowed": False,
                "technical_context_filter_allowed": False,
                "technical_manual_checklist_allowed": not technical_violation,
                "official_adoption_allowed": False,
                "broker_action_allowed": False,
            },
        )
    if not missing_dram:
        write_json(
            repo / "outputs/v21/V21.234_MINIMAL_MOOMOO_ONLY_DAILY_RESEARCH_CHAIN/v21_234_summary.json",
            {
                "final_status": "PASS_V21_234_DAILY_CHAIN_READY",
                "final_decision": "DRAM_DAILY_CHAIN_READY",
                "latest_dram_plan_currentness": "CURRENT",
                "broker_action_allowed": False,
                "trade_plan_mutation_allowed": False,
            },
        )
    protected = repo / "protected.txt"
    protected.write_text("protected", encoding="utf-8")
    before = hashlib.sha256(protected.read_bytes()).hexdigest()
    return repo, protected, before


def test_missing_v21_251_summary(tmp_path):
    repo, _, _ = seed(tmp_path, missing251=True)
    s = m.run(repo)
    assert s["final_status"] == "FAIL_V21_252_DRAM_ONLY_BOUNDARY_INPUT_MISSING"
    assert s["missing_input_count"] == 1


def test_missing_v21_250_summary(tmp_path):
    repo, _, _ = seed(tmp_path, missing250=True)
    s = m.run(repo)
    assert s["final_status"] == "FAIL_V21_252_DRAM_ONLY_BOUNDARY_INPUT_MISSING"
    assert s["missing_input_count"] == 1


def test_missing_latest_dram_summary_warns(tmp_path):
    repo, _, _ = seed(tmp_path, missing_dram=True)
    s = m.run(repo)
    assert s["final_status"] == "WARN_V21_252_DRAM_ONLY_BOUNDARY_READY_WITH_MISSING_DRAM_SUMMARY"
    assert s["latest_dram_summary_found"] is False
    assert s["error_count"] == 0


def test_dram_primary_focus_active(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    assert s["dram_primary_focus_active"] is True


def test_strategy_governance_research_context_only(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    data = rows(repo / m.OUT_REL / "strategy_governance_research_context_block.csv")
    assert s["strategy_governance_research_context_only"] is True
    assert any(r["allowed_use"] == "RESEARCH_CONTEXT_ONLY" for r in data)


def test_strategy_governance_risk_review_only(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    data = rows(repo / m.OUT_REL / "strategy_governance_research_context_block.csv")
    assert s["strategy_governance_risk_review_only"] is True
    assert any(r["allowed_use"] == "RISK_REVIEW_ONLY" for r in data)


def test_technical_checklist_observation_only(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    data = rows(repo / m.OUT_REL / "technical_freeze_boundary_enforcement.csv")
    assert s["technical_checklist_observation_only"] is True
    assert any(r["boundary_item"] == "technical_manual_checklist_allowed" and r["observed"] == "True" for r in data)


def test_conflict_resolution_policy_generation(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    data = rows(repo / m.OUT_REL / "strategy_governance_dram_conflict_resolution.csv")
    assert s["conflict_policy_count"] == 5
    assert any(r["conflict_case"] == "DRAM_VS_STRATEGY_GOVERNANCE" for r in data)


def test_daily_chain_integration_recommendation_generation(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    data = rows(repo / m.OUT_REL / "daily_chain_integration_recommendation.csv")
    assert s["daily_chain_recommendation_count"] == 4
    assert any(r["recommendation"] == "DO_NOT_MODIFY_DRAM_TRADE_PLAN" for r in data)


def test_no_automatic_ticker_position_trade_gates(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    assert s["automatic_ticker_replacement_allowed"] is False
    assert s["automatic_position_increase_allowed"] is False
    assert s["automatic_trade_trigger_allowed"] is False


def test_no_broker_ranking_weight_trade_plan_mutation(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    assert s["broker_action_allowed"] is False
    assert s["ranking_mutation_allowed"] is False
    assert s["weight_update_allowed"] is False
    assert s["trade_plan_mutation_allowed"] is False


def test_boundary_policy_contains_no_go_labels(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    labels = {r["boundary_label"]: r["allowed_or_active"] for r in rows(repo / m.OUT_REL / "dram_only_boundary_policy.csv")}
    assert labels["NO_AUTO_TICKER_REPLACEMENT"] == "False"
    assert labels["NO_AUTO_POSITION_INCREASE"] == "False"
    assert labels["NO_AUTO_TRADE_TRIGGER"] == "False"
    assert labels["NO_RANKING_MUTATION"] == "False"
    assert labels["NO_WEIGHT_UPDATE"] == "False"
    assert labels["NO_BROKER_ACTION"] == "False"


def test_technical_gate_violation_fails(tmp_path):
    repo, _, _ = seed(tmp_path, technical_violation=True)
    s = m.run(repo)
    assert s["final_status"] == "FAIL_V21_252_DRAM_ONLY_BOUNDARY_GATE_VIOLATION"


def test_summary_json_schema(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    payload = json.loads((repo / m.OUT_REL / "v21_252_summary.json").read_text(encoding="utf-8"))
    for k in [
        "final_status",
        "final_decision",
        "dram_primary_focus_active",
        "strategy_governance_research_context_only",
        "strategy_governance_risk_review_only",
        "technical_checklist_observation_only",
        "current_regime_shadow_primary",
        "long_history_fallback",
        "high_return_watch_only",
        "conflict_policy_count",
        "daily_chain_recommendation_count",
        "latest_dram_summary_found",
        "latest_dram_final_status",
        "latest_dram_final_decision",
        "latest_dram_plan_currentness",
        "research_only",
        "official_adoption_allowed",
        "broker_action_allowed",
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
