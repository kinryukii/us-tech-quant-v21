from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import re
from pathlib import Path

P = Path(__file__).with_name("v21_251_strategy_weight_governance_from_v21_255_and_current_regime_r1.py")
S = importlib.util.spec_from_file_location("m251", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, object]] | None = None) -> None:
    rows = rows or [{"x": 1}]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, list(rows[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def seed(tmp_path: Path, missing255: bool = False, missing250: bool = False, optional_missing: bool = False, freeze_violation: bool = False):
    repo = tmp_path / "repo"
    if not missing255:
        write_json(
            repo / m.V255_REL / "v21_255_summary.json",
            {
                "recommended_current_regime_strategy": "E_R3_QUALITY_RISK_REPAIR_BASE",
                "recommended_fallback_strategy": "E_R2_CONSERVATIVE_DEFENSIVE_RETURN",
                "recommended_parallel_watch_strategy": "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL",
                "strategies_compared": [
                    "E_R3_QUALITY_RISK_REPAIR_BASE",
                    "E_R2_CONSERVATIVE_DEFENSIVE_RETURN",
                    "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL",
                    "DRAM",
                    "A1",
                    "CUSTOM_DIAGNOSTIC",
                ],
                "official_adoption_allowed": False,
                "broker_action_allowed": False,
            },
        )
        if not optional_missing:
            for name in [
                "strategy_period_decision_matrix.csv",
                "strategy_backtest_comparison_master.csv",
                "strategy_factor_weight_effectiveness_matrix.csv",
            ]:
                write_csv(repo / m.V255_REL / name)
    if not missing250:
        write_json(
            repo / m.V250_REL / "v21_250_summary.json",
            {
                "model_entry_allowed": freeze_violation,
                "technical_timing_overlay_allowed": False,
                "technical_context_filter_allowed": False,
                "technical_manual_checklist_allowed": True,
                "official_adoption_allowed": False,
                "broker_action_allowed": False,
            },
        )
    protected = repo / "protected.txt"
    protected.write_text("protected", encoding="utf-8")
    before = hashlib.sha256(protected.read_bytes()).hexdigest()
    return repo, protected, before


def test_missing_v21_255_summary(tmp_path):
    repo, _, _ = seed(tmp_path, missing255=True)
    s = m.run(repo)
    assert s["final_status"] == "FAIL_V21_251_STRATEGY_GOVERNANCE_INPUT_MISSING"
    assert s["missing_input_count"] == 1


def test_missing_v21_250_summary(tmp_path):
    repo, _, _ = seed(tmp_path, missing250=True)
    s = m.run(repo)
    assert s["final_status"] == "FAIL_V21_251_STRATEGY_GOVERNANCE_INPUT_MISSING"
    assert s["missing_input_count"] == 1


def test_v21_255_role_extraction(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    assert s["current_regime_shadow_primary"] == "E_R3_QUALITY_RISK_REPAIR_BASE"
    assert s["long_history_fallback"] == "E_R2_CONSERVATIVE_DEFENSIVE_RETURN"
    assert s["high_return_watch_only"] == "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"


def test_strategy_role_map_generation(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    data = rows(repo / m.OUT_REL / "strategy_governance_role_map.csv")
    roles = {r["strategy"]: r["governance_role"] for r in data}
    assert roles["E_R3_QUALITY_RISK_REPAIR_BASE"] == "CURRENT_REGIME_SHADOW_PRIMARY"
    assert roles["E_R2_CONSERVATIVE_DEFENSIVE_RETURN"] == "LONG_HISTORY_FALLBACK"
    assert roles["NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"] == "HIGH_RETURN_WATCH_ONLY"
    assert roles["CUSTOM_DIAGNOSTIC"] == "DIAGNOSTIC_ONLY"


def test_switch_condition_candidate_generation(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    data = rows(repo / m.OUT_REL / "strategy_switch_condition_candidates.csv")
    assert s["switch_condition_count"] == 4
    assert any(r["condition_name"] == "DRAM_ONLY_PREFERENCE_REMAINS_DOMINANT" for r in data)


def test_dram_compatibility_audit(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    data = rows(repo / m.OUT_REL / "dram_compatibility_audit.csv")
    assert s["dram_compatible"] is True
    assert {r["passed"] for r in data} == {"True"}


def test_technical_freeze_enforcement(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    data = rows(repo / m.OUT_REL / "technical_freeze_enforcement_audit.csv")
    assert s["technical_freeze_enforced"] is True
    assert {r["passed"] for r in data} == {"True"}


def test_technical_freeze_violation_fails(tmp_path):
    repo, _, _ = seed(tmp_path, freeze_violation=True)
    s = m.run(repo)
    assert s["final_status"] == "FAIL_V21_251_STRATEGY_GOVERNANCE_GATE_VIOLATION"


def test_no_go_gates_enforced(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["weight_update_allowed"] is False
    assert s["ranking_mutation_allowed"] is False
    assert s["trade_plan_mutation_allowed"] is False
    data = rows(repo / m.OUT_REL / "strategy_weight_governance_no_go_audit.csv")
    assert {r["passed"] for r in data} == {"True"}


def test_optional_inputs_missing_warns(tmp_path):
    repo, _, _ = seed(tmp_path, optional_missing=True)
    s = m.run(repo)
    assert s["final_status"] == "WARN_V21_251_STRATEGY_GOVERNANCE_READY_WITH_MISSING_OPTIONAL_INPUTS"
    assert s["error_count"] == 0


def test_summary_json_schema(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    payload = json.loads((repo / m.OUT_REL / "v21_251_summary.json").read_text(encoding="utf-8"))
    for k in [
        "final_status",
        "final_decision",
        "strategy_count",
        "role_mapped_strategy_count",
        "current_regime_shadow_primary",
        "long_history_fallback",
        "high_return_watch_only",
        "switch_condition_count",
        "dram_compatible",
        "technical_freeze_enforced",
        "research_only",
        "official_adoption_allowed",
        "broker_action_allowed",
        "factor_promotion_allowed",
        "weight_update_allowed",
        "ranking_mutation_allowed",
        "trade_plan_mutation_allowed",
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
