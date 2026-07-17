from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_030_etf_option_universe_registry.py")
SPEC = importlib.util.spec_from_file_location("v22_030", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


REQUIRED_FILES = [
    "v22_etf_option_universe_registry.csv",
    "v22_etf_option_universe_group_summary.csv",
    "v22_etf_option_strategy_permission_registry.csv",
    "v22_etf_option_exclusion_registry.csv",
    "v22_etf_option_universe_summary.json",
    "v22_etf_option_universe_risk_gate.json",
    "V22.030_etf_option_universe_registry_report.txt",
]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def run_stage(tmp_path: Path) -> tuple[Path, dict]:
    repo = tmp_path / "repo"
    payload = module.run(repo)
    return repo, payload


def test_required_output_files_are_created(tmp_path):
    repo, _ = run_stage(tmp_path)
    for filename in REQUIRED_FILES:
        assert (repo / module.OUT_REL / filename).exists()


def test_summary_counts_and_decision(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_etf_option_universe_summary.json").read_text(encoding="utf-8"))
    assert summary["final_status"] == "PASS_V22_030_ETF_OPTION_UNIVERSE_REGISTRY_READY"
    assert summary["final_decision"] == "ETF_OPTION_UNIVERSE_REGISTRY_READY_RESEARCH_ONLY"
    assert summary["total_universe_count"] == 13
    assert summary["core_etf_count"] == 5
    assert summary["secondary_leveraged_long_count"] == 4
    assert summary["secondary_leveraged_inverse_count"] == 4
    assert summary["leveraged_etf_count"] == 8
    assert summary["inverse_leveraged_etf_count"] == 4
    assert summary["high_risk_secondary_count"] == 8
    assert summary["option_chain_fetch_allowed_count"] == 0
    assert summary["broker_action_allowed_count"] == 0
    assert summary["official_adoption_allowed_count"] == 0
    assert summary["trade_allowed_count"] == 0


def test_universe_tickers_groups_and_leveraged_flags(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_etf_option_universe_registry.csv")
    by_ticker = {row["ticker"]: row for row in rows}
    expected = {"SMH", "SOXX", "QQQ", "SPY", "DIA", "SOXL", "TQQQ", "SPXL", "UDOW", "SOXS", "SQQQ", "SPXS", "SDOW"}
    assert expected == set(by_ticker)
    for ticker in ["SOXL", "TQQQ", "SPXL", "UDOW"]:
        assert by_ticker[ticker]["universe_group"] == "SECONDARY_LEVERAGED_LONG"
    for ticker in ["SOXS", "SQQQ", "SPXS", "SDOW"]:
        assert by_ticker[ticker]["universe_group"] == "SECONDARY_LEVERAGED_INVERSE"
    for ticker in ["SOXL", "TQQQ", "SPXL", "UDOW", "SOXS", "SQQQ", "SPXS", "SDOW"]:
        assert by_ticker[ticker]["high_risk_secondary_flag"] == "True"
        assert by_ticker[ticker]["manual_review_required"] == "True"


def test_exclusions_and_strategy_permissions(tmp_path):
    repo, _ = run_stage(tmp_path)
    exclusions = read_rows(repo / module.OUT_REL / "v22_etf_option_exclusion_registry.csv")
    assert {"SPX", "XSP", "NDX", "XND", "RUT", "RUTW"} == {row["excluded_symbol"] for row in exclusions}
    strategies = {row["strategy_name"]: row for row in read_rows(repo / module.OUT_REL / "v22_etf_option_strategy_permission_registry.csv")}
    for strategy in ["LONG_CALL", "LONG_PUT", "DEBIT_CALL_SPREAD", "DEBIT_PUT_SPREAD"]:
        assert strategies[strategy]["permission_status"] == "ALLOWED_INITIAL_RESEARCH"
    for strategy in ["NAKED_SHORT_CALL", "NAKED_SHORT_PUT"]:
        assert strategies[strategy]["permission_status"] == "BLOCKED"


def test_summary_gates_are_false(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_etf_option_universe_summary.json").read_text(encoding="utf-8"))
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
    assert summary["protected_outputs_modified"] is False


def test_module_has_no_broker_network_process_or_mutation_imports():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    banned_modules = {"moomoo", "futu", "yfinance", "requests", "urllib", "http", "socket", "subprocess", "shutil", "os"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(banned_modules)


def test_module_writes_only_under_v22_030_output_dir(tmp_path):
    repo, payload = run_stage(tmp_path)
    expected = (repo / module.OUT_REL).resolve()
    assert payload["module_id"] == "V22.030"
    for path in repo.rglob("*"):
        if path.is_file():
            assert expected in path.resolve().parents


def test_no_universe_row_allows_broker_adoption_or_trade(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_etf_option_universe_registry.csv")
    assert rows
    for row in rows:
        assert row["broker_action_allowed"] == "False"
        assert row["official_adoption_allowed"] == "False"
        assert row["trade_allowed"] == "False"
