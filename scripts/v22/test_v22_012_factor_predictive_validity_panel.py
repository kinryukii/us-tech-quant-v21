from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_012_factor_predictive_validity_panel.py")
SPEC = importlib.util.spec_from_file_location("v22_012", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


REQUIRED_FILES = [
    "v22_factor_predictive_validity_panel.csv",
    "v22_factor_predictive_validity_by_horizon.csv",
    "v22_factor_predictive_validity_source_audit.csv",
    "v22_factor_predictive_validity_readiness_summary.csv",
    "v22_factor_predictive_validity_summary.json",
    "v22_factor_predictive_validity_risk_gate.json",
    "V22.012_factor_predictive_validity_panel_report.txt",
]

REGISTRY_FIELDNAMES = [
    "item_id",
    "item_name",
    "item_type",
    "family",
    "current_evidence_level",
    "evidence_level_label",
    "evidence_source_modules",
    "current_status",
    "forward_maturity_status",
    "regime_robustness_status",
    "coverage_status",
    "multiple_testing_risk",
    "redundancy_risk",
    "adoption_eligible",
    "official_adoption_allowed",
    "broker_action_allowed",
    "trade_allowed",
    "research_only",
    "next_required_validation",
    "reason",
]

COVERAGE_FIELDNAMES = [
    "item_id",
    "item_name",
    "item_type",
    "family",
    "evidence_level_label",
    "coverage_source_status",
    "coverage_status",
    "missingness_risk",
    "eligible_for_predictive_validity",
    "local_source_count",
    "primary_source_paths",
    "detected_columns",
    "date_column_detected",
    "ticker_column_detected",
    "score_or_signal_column_detected",
    "row_count_estimate",
    "ticker_count_estimate",
    "date_count_estimate",
    "latest_date_detected",
    "source_scan_mode",
    "adoption_eligible",
    "official_adoption_allowed",
    "broker_action_allowed",
    "trade_allowed",
    "research_only",
    "next_required_validation",
    "reason",
]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def registry_row(item_id: str, item_type: str, family: str) -> dict[str, object]:
    return {
        "item_id": item_id,
        "item_name": item_id,
        "item_type": item_type,
        "family": family,
        "current_evidence_level": 2,
        "evidence_level_label": "LEVEL_2_PIT_LITE_BACKTEST",
        "evidence_source_modules": "TEST_LOCAL",
        "current_status": "TEST",
        "forward_maturity_status": "PENDING",
        "regime_robustness_status": "NOT_CONFIRMED",
        "coverage_status": "TEST",
        "multiple_testing_risk": "MEDIUM",
        "redundancy_risk": "MEDIUM",
        "adoption_eligible": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "trade_allowed": False,
        "research_only": True,
        "next_required_validation": "TEST_NEXT",
        "reason": "test registry row",
    }


def coverage_row(item_id: str, item_type: str, family: str, eligible: bool) -> dict[str, object]:
    return {
        "item_id": item_id,
        "item_name": item_id,
        "item_type": item_type,
        "family": family,
        "evidence_level_label": "LEVEL_2_PIT_LITE_BACKTEST",
        "coverage_source_status": "SOURCE_FOUND" if eligible else "SOURCE_PLACEHOLDER_ONLY",
        "coverage_status": "COVERAGE_READY" if eligible else "COVERAGE_PLACEHOLDER_ONLY",
        "missingness_risk": "LOW" if eligible else "HIGH",
        "eligible_for_predictive_validity": eligible,
        "local_source_count": 1 if eligible else 0,
        "primary_source_paths": "",
        "detected_columns": "",
        "date_column_detected": eligible,
        "ticker_column_detected": eligible,
        "score_or_signal_column_detected": eligible,
        "row_count_estimate": 10 if eligible else 0,
        "ticker_count_estimate": 2 if eligible else 0,
        "date_count_estimate": 2 if eligible else 0,
        "latest_date_detected": "2026-07-01" if eligible else "",
        "source_scan_mode": "TEST",
        "adoption_eligible": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "trade_allowed": False,
        "research_only": True,
        "next_required_validation": "TEST_NEXT",
        "reason": "test coverage row",
    }


def seed_required_inputs(repo: Path) -> list[str]:
    specs = [
        ("RSI", "TECHNICAL_SUBFACTOR", "TECHNICAL", True),
        ("KDJ", "TECHNICAL_SUBFACTOR", "TECHNICAL", True),
        ("MACD", "TECHNICAL_SUBFACTOR", "TECHNICAL", True),
        ("BOLLINGER_BAND_7_LINE", "TECHNICAL_SUBFACTOR", "TECHNICAL", True),
        ("E_R3_QUALITY_RISK_REPAIR_BASE", "STRATEGY_RANKING_SYSTEM", "STRATEGY", True),
        ("NEW_FACTOR_LITE", "STRATEGY_RANKING_SYSTEM", "STRATEGY", True),
        ("DRAM_DAILY_PLAN", "DRAM_SYSTEM", "DRAM", True),
        ("ETF_OPTION_LONG_CALL", "ETF_OPTION_PLACEHOLDER", "ETF_OPTIONS", False),
        ("ETF_OPTION_LONG_PUT", "ETF_OPTION_PLACEHOLDER", "ETF_OPTIONS", False),
    ]
    write_csv(repo / module.REGISTRY_INPUT, REGISTRY_FIELDNAMES, [registry_row(item_id, item_type, family) for item_id, item_type, family, _eligible in specs])
    write_csv(repo / module.COVERAGE_INPUT, COVERAGE_FIELDNAMES, [coverage_row(item_id, item_type, family, eligible) for item_id, item_type, family, eligible in specs])
    return [item_id for item_id, _item_type, _family, _eligible in specs]


def seed_optional_sources(repo: Path) -> None:
    write_csv(
        repo / "outputs" / "v21" / "V21.247_TECHNICAL_SUBFACTOR_EFFECTIVENESS_PIT_LITE_AUDIT" / "technical.csv",
        ["date", "ticker", "rsi_signal", "macd_score", "forward_5d_return"],
        [{"date": "2026-07-01", "ticker": "AMD", "rsi_signal": 1, "macd_score": 2, "forward_5d_return": 0.01}],
    )
    write_csv(
        repo / "outputs" / "v21" / "V21.255_DETAILED_STRATEGY_BACKTEST_FACTOR_WEIGHT_COMPARISON" / "strategy.csv",
        ["date", "ticker", "strategy_score", "top_minus_bottom_return"],
        [{"date": "2026-07-01", "ticker": "NVDA", "strategy_score": 1, "top_minus_bottom_return": 0.02}],
    )
    write_csv(
        repo / "outputs" / "v21" / "V21.232_DRAM" / "dram.csv",
        ["date", "trigger_signal", "hit_rate"],
        [{"date": "2026-07-01", "trigger_signal": "NO_TRADE", "hit_rate": 0.5}],
    )


def run_stage(tmp_path: Path) -> tuple[Path, dict]:
    repo = tmp_path / "repo"
    seed_required_inputs(repo)
    seed_optional_sources(repo)
    payload = module.run(repo)
    return repo, payload


def test_required_output_files_are_created(tmp_path):
    repo, _ = run_stage(tmp_path)
    out = repo / module.OUT_REL
    for filename in REQUIRED_FILES:
        assert (out / filename).exists()


def test_summary_decision_inputs_and_counts(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_factor_predictive_validity_summary.json").read_text(encoding="utf-8"))
    assert summary["final_decision"] == "FACTOR_PREDICTIVE_VALIDITY_PANEL_READY_RESEARCH_ONLY"
    assert summary["registry_input_exists"] is True
    assert summary["coverage_input_exists"] is True
    assert summary["evaluated_item_count"] == summary["registered_item_count"]


def test_required_items_exist_in_panel(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_factor_predictive_validity_panel.csv")
    item_ids = {row["item_id"] for row in rows}
    for item_id in [
        "RSI",
        "KDJ",
        "MACD",
        "BOLLINGER_BAND_7_LINE",
        "E_R3_QUALITY_RISK_REPAIR_BASE",
        "NEW_FACTOR_LITE",
        "DRAM_DAILY_PLAN",
        "ETF_OPTION_LONG_CALL",
        "ETF_OPTION_LONG_PUT",
    ]:
        assert item_id in item_ids


def test_option_placeholders_are_not_adoption_eligible(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_factor_predictive_validity_panel.csv")
    by_id = {row["item_id"]: row for row in rows}
    for item_id in ["ETF_OPTION_LONG_CALL", "ETF_OPTION_LONG_PUT"]:
        assert by_id[item_id]["predictive_validity_status"] == "PLACEHOLDER_ONLY"
        assert by_id[item_id]["adoption_eligible_after_v22_012"] == "False"


def test_action_counts_are_zero(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_factor_predictive_validity_summary.json").read_text(encoding="utf-8"))
    assert summary["official_adoption_allowed_count"] == 0
    assert summary["broker_action_allowed_count"] == 0
    assert summary["trade_allowed_count"] == 0


def test_summary_no_action_and_factor_gates_false(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_factor_predictive_validity_summary.json").read_text(encoding="utf-8"))
    for key in [
        "broker_action_allowed",
        "official_adoption_allowed",
        "trade_allowed",
        "moomoo_connection_allowed",
        "market_data_fetch_allowed",
        "option_chain_fetch_allowed",
        "daily_chain_execution_allowed",
        "factor_promotion_allowed",
        "factor_weight_change_allowed",
    ]:
        assert summary[key] is False


def test_module_has_no_broker_network_process_or_mutation_imports():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    banned_modules = {
        "moomoo",
        "futu",
        "yfinance",
        "requests",
        "urllib",
        "http",
        "socket",
        "subprocess",
        "shutil",
        "os",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(banned_modules)


def test_module_writes_only_under_v22_012_output_dir(tmp_path):
    repo, payload = run_stage(tmp_path)
    expected = (repo / module.OUT_REL).resolve()
    allowed_seed_files = {
        (repo / module.REGISTRY_INPUT).resolve(),
        (repo / module.COVERAGE_INPUT).resolve(),
        (repo / "outputs" / "v21" / "V21.247_TECHNICAL_SUBFACTOR_EFFECTIVENESS_PIT_LITE_AUDIT" / "technical.csv").resolve(),
        (repo / "outputs" / "v21" / "V21.255_DETAILED_STRATEGY_BACKTEST_FACTOR_WEIGHT_COMPARISON" / "strategy.csv").resolve(),
        (repo / "outputs" / "v21" / "V21.232_DRAM" / "dram.csv").resolve(),
    }
    assert Path(payload["output_dir"]).resolve() == expected
    assert expected.name == "V22.012_FACTOR_PREDICTIVE_VALIDITY_PANEL"
    for path in repo.rglob("*"):
        if path.is_file() and path.resolve() not in allowed_seed_files:
            assert expected in path.resolve().parents


def test_no_panel_row_allows_official_adoption_broker_action_or_trade(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_factor_predictive_validity_panel.csv")
    assert rows
    for row in rows:
        assert row["official_adoption_allowed"] == "False"
        assert row["broker_action_allowed"] == "False"
        assert row["trade_allowed"] == "False"


def test_by_horizon_contains_standard_horizons(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_factor_predictive_validity_by_horizon.csv")
    horizons = {row["horizon"] for row in rows}
    assert {"1D", "3D", "5D", "10D", "20D"}.issubset(horizons)
