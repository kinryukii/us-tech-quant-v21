from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_010_factor_evidence_level_registry.py")
SPEC = importlib.util.spec_from_file_location("v22_010", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


REQUIRED_FILES = [
    "v22_factor_evidence_level_registry.csv",
    "v22_factor_evidence_level_definitions.csv",
    "v22_strategy_evidence_summary.csv",
    "v22_factor_evidence_registry_summary.json",
    "v22_factor_evidence_registry_risk_gate.json",
    "V22.010_factor_evidence_level_registry_report.txt",
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
    out = repo / module.OUT_REL
    for filename in REQUIRED_FILES:
        assert (out / filename).exists()


def test_final_status_decision_and_evidence_level_count(tmp_path):
    repo, payload = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_factor_evidence_registry_summary.json").read_text(encoding="utf-8"))
    assert payload["final_status"] == "PASS_V22_010_FACTOR_EVIDENCE_LEVEL_REGISTRY_READY"
    assert summary["final_status"] == "PASS_V22_010_FACTOR_EVIDENCE_LEVEL_REGISTRY_READY"
    assert summary["final_decision"] == "FACTOR_EVIDENCE_LEVEL_REGISTRY_READY_RESEARCH_ONLY"
    assert summary["evidence_level_count"] == 9


def test_etf_option_placeholders_exist_and_are_not_adoption_eligible(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_factor_evidence_level_registry.csv")
    by_id = {row["item_id"]: row for row in rows}
    for item_id in [
        "ETF_OPTION_LONG_CALL",
        "ETF_OPTION_LONG_PUT",
        "ETF_OPTION_DEBIT_CALL_SPREAD",
        "ETF_OPTION_DEBIT_PUT_SPREAD",
        "ETF_OPTION_LONG_STRADDLE_RESEARCH",
        "ETF_OPTION_LONG_STRANGLE_RESEARCH",
    ]:
        assert item_id in by_id
        assert by_id[item_id]["adoption_eligible"] == "False"
        assert by_id[item_id]["current_evidence_level"] == "0"


def test_required_technical_and_strategy_items_exist(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_factor_evidence_level_registry.csv")
    item_ids = {row["item_id"] for row in rows}
    for item_id in ["RSI", "KDJ", "MACD", "BOLLINGER_BAND_7_LINE"]:
        assert item_id in item_ids
    assert "E_R3_QUALITY_RISK_REPAIR_BASE" in item_ids
    assert "NEW_FACTOR_LITE" in item_ids


def test_action_counts_are_zero(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_factor_evidence_registry_summary.json").read_text(encoding="utf-8"))
    assert summary["official_adoption_allowed_count"] == 0
    assert summary["broker_action_allowed_count"] == 0
    assert summary["trade_allowed_count"] == 0


def test_summary_no_action_gates_false(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_factor_evidence_registry_summary.json").read_text(encoding="utf-8"))
    for key in [
        "broker_action_allowed",
        "official_adoption_allowed",
        "trade_allowed",
        "moomoo_connection_allowed",
        "market_data_fetch_allowed",
        "option_chain_fetch_allowed",
        "daily_chain_execution_allowed",
    ]:
        assert summary[key] is False
    assert summary["protected_outputs_modified"] is False


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
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(banned_modules)


def test_module_writes_only_under_v22_010_output_dir(tmp_path):
    repo, payload = run_stage(tmp_path)
    expected = (repo / module.OUT_REL).resolve()
    assert Path(payload["output_dir"]).resolve() == expected
    assert expected.name == "V22.010_FACTOR_EVIDENCE_LEVEL_REGISTRY"
    for path in repo.rglob("*"):
        if path.is_file():
            assert expected in path.resolve().parents


def test_no_registry_item_allows_official_adoption_broker_action_or_trade(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_factor_evidence_level_registry.csv")
    assert rows
    for row in rows:
        assert row["official_adoption_allowed"] == "False"
        assert row["broker_action_allowed"] == "False"
        assert row["trade_allowed"] == "False"
