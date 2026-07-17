from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_011_factor_coverage_and_missingness_audit.py")
SPEC = importlib.util.spec_from_file_location("v22_011", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


REQUIRED_FILES = [
    "v22_factor_coverage_audit.csv",
    "v22_factor_missingness_audit.csv",
    "v22_factor_coverage_source_file_audit.csv",
    "v22_factor_coverage_readiness_summary.csv",
    "v22_factor_coverage_and_missingness_summary.json",
    "v22_factor_coverage_and_missingness_risk_gate.json",
    "V22.011_factor_coverage_and_missingness_audit_report.txt",
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


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


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


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def seed_registry(repo: Path) -> None:
    rows = [
        registry_row("RSI", "TECHNICAL_SUBFACTOR", "TECHNICAL"),
        registry_row("KDJ", "TECHNICAL_SUBFACTOR", "TECHNICAL"),
        registry_row("MACD", "TECHNICAL_SUBFACTOR", "TECHNICAL"),
        registry_row("BOLLINGER_BAND_7_LINE", "TECHNICAL_SUBFACTOR", "TECHNICAL"),
        registry_row("E_R3_QUALITY_RISK_REPAIR_BASE", "STRATEGY_RANKING_SYSTEM", "STRATEGY"),
        registry_row("NEW_FACTOR_LITE", "STRATEGY_RANKING_SYSTEM", "STRATEGY"),
        registry_row("DRAM_DAILY_PLAN", "DRAM_SYSTEM", "DRAM"),
        registry_row("ETF_OPTION_LONG_CALL", "ETF_OPTION_PLACEHOLDER", "ETF_OPTIONS"),
        registry_row("ETF_OPTION_LONG_PUT", "ETF_OPTION_PLACEHOLDER", "ETF_OPTIONS"),
    ]
    write_csv(repo / module.REGISTRY_INPUT, REGISTRY_FIELDNAMES, rows)


def seed_optional_sources(repo: Path) -> None:
    write_csv(
        repo / "outputs" / "v21" / "V21.247_TECHNICAL_SUBFACTOR_EFFECTIVENESS_PIT_LITE_AUDIT" / "technical.csv",
        ["date", "ticker", "rsi_signal", "macd_score", "kdj_score"],
        [{"date": "2026-07-01", "ticker": "AMD", "rsi_signal": 1, "macd_score": 2, "kdj_score": 3}],
    )
    write_csv(
        repo / "outputs" / "v21" / "V21.255_DETAILED_STRATEGY_BACKTEST_FACTOR_WEIGHT_COMPARISON" / "strategy.csv",
        ["date", "ticker", "strategy_score", "weight"],
        [{"date": "2026-07-01", "ticker": "NVDA", "strategy_score": 1, "weight": 0.5}],
    )
    write_csv(
        repo / "outputs" / "v21" / "V21.232_DRAM" / "dram.csv",
        ["date", "trigger_signal", "plan_score"],
        [{"date": "2026-07-01", "trigger_signal": "NO_TRADE", "plan_score": 1}],
    )


def run_stage(tmp_path: Path) -> tuple[Path, dict]:
    repo = tmp_path / "repo"
    seed_registry(repo)
    seed_optional_sources(repo)
    payload = module.run(repo)
    return repo, payload


def test_required_output_files_are_created(tmp_path):
    repo, _ = run_stage(tmp_path)
    out = repo / module.OUT_REL
    for filename in REQUIRED_FILES:
        assert (out / filename).exists()


def test_summary_decision_registry_and_counts(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_factor_coverage_and_missingness_summary.json").read_text(encoding="utf-8"))
    assert summary["final_decision"] == "FACTOR_COVERAGE_AND_MISSINGNESS_AUDIT_READY_RESEARCH_ONLY"
    assert summary["registry_input_exists"] is True
    assert summary["audited_item_count"] == summary["registered_item_count"]


def test_option_placeholders_not_predictive_eligible(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_factor_coverage_and_missingness_summary.json").read_text(encoding="utf-8"))
    assert summary["etf_option_placeholder_count"] == 2
    assert summary["etf_option_placeholder_eligible_count"] == 0
    rows = read_rows(repo / module.OUT_REL / "v22_factor_coverage_audit.csv")
    by_id = {row["item_id"]: row for row in rows}
    for item_id in ["ETF_OPTION_LONG_CALL", "ETF_OPTION_LONG_PUT"]:
        assert by_id[item_id]["coverage_status"] in {"COVERAGE_PLACEHOLDER_ONLY", "COVERAGE_MISSING"}
        assert by_id[item_id]["eligible_for_predictive_validity"] == "False"


def test_action_counts_are_zero(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_factor_coverage_and_missingness_summary.json").read_text(encoding="utf-8"))
    assert summary["official_adoption_allowed_count"] == 0
    assert summary["broker_action_allowed_count"] == 0
    assert summary["trade_allowed_count"] == 0


def test_summary_no_action_and_factor_gates_false(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_factor_coverage_and_missingness_summary.json").read_text(encoding="utf-8"))
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


def test_required_items_exist_in_coverage_audit(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_factor_coverage_audit.csv")
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


def test_module_writes_only_under_v22_011_output_dir(tmp_path):
    repo, payload = run_stage(tmp_path)
    expected = (repo / module.OUT_REL).resolve()
    allowed_seed_files = {
        (repo / module.REGISTRY_INPUT).resolve(),
        (repo / "outputs" / "v21" / "V21.247_TECHNICAL_SUBFACTOR_EFFECTIVENESS_PIT_LITE_AUDIT" / "technical.csv").resolve(),
        (repo / "outputs" / "v21" / "V21.255_DETAILED_STRATEGY_BACKTEST_FACTOR_WEIGHT_COMPARISON" / "strategy.csv").resolve(),
        (repo / "outputs" / "v21" / "V21.232_DRAM" / "dram.csv").resolve(),
    }
    assert Path(payload["output_dir"]).resolve() == expected
    assert expected.name == "V22.011_FACTOR_COVERAGE_AND_MISSINGNESS_AUDIT"
    for path in repo.rglob("*"):
        if path.is_file() and path.resolve() not in allowed_seed_files:
            assert expected in path.resolve().parents


def test_no_coverage_row_allows_official_adoption_broker_action_or_trade(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_factor_coverage_audit.csv")
    assert rows
    for row in rows:
        assert row["official_adoption_allowed"] == "False"
        assert row["broker_action_allowed"] == "False"
        assert row["trade_allowed"] == "False"
