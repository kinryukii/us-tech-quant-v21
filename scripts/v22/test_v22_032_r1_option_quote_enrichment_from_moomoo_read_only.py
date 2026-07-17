from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_032_r1_option_quote_enrichment_from_moomoo_read_only.py")
SPEC = importlib.util.spec_from_file_location("v22_032_r1", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


REQUIRED_FILES = [
    "v22_option_quote_enrichment_raw.csv",
    "v22_option_quote_enrichment_clean.csv",
    "v22_option_quote_enrichment_underlying_audit.csv",
    "v22_option_quote_enrichment_fetch_audit.csv",
    "v22_option_quote_enrichment_field_coverage_audit.csv",
    "v22_option_quote_enrichment_summary.json",
    "v22_option_quote_enrichment_risk_gate.json",
    "V22.032_R1_option_quote_enrichment_from_moomoo_read_only_report.txt",
]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def seed_inputs(repo: Path) -> None:
    rows = [
        {
            "underlying": "QQQ",
            "universe_group": "CORE_ETF",
            "universe_tier": "CORE",
            "theme_bucket": "NASDAQ",
            "leveraged_flag": False,
            "inverse_flag": False,
            "leverage_multiple": 1,
            "expiration": "2026-07-10",
            "dte": "",
            "strike": "500",
            "call_put": "CALL",
            "option_code": "US.QQQ260710C500000",
            "option_name": "QQQ 260710 500.00C",
        },
        {
            "underlying": "SPY",
            "universe_group": "CORE_ETF",
            "universe_tier": "CORE",
            "theme_bucket": "SP500",
            "leveraged_flag": False,
            "inverse_flag": False,
            "leverage_multiple": 1,
            "expiration": "2026-07-10",
            "dte": "",
            "strike": "600",
            "call_put": "PUT",
            "option_code": "US.SPY260710P600000",
            "option_name": "SPY 260710 600.00P",
        },
    ]
    write_csv(repo / module.SOURCE_CLEAN_INPUT, list(rows[0].keys()), rows)
    (repo / module.SOURCE_SUMMARY_INPUT).parent.mkdir(parents=True, exist_ok=True)
    (repo / module.SOURCE_SUMMARY_INPUT).write_text(json.dumps({"clean_contract_row_count": 2, "execution_mode": "EXECUTE_READ_ONLY"}), encoding="utf-8")
    (repo / module.V22_033_SUMMARY_INPUT).parent.mkdir(parents=True, exist_ok=True)
    (repo / module.V22_033_SUMMARY_INPUT).write_text(json.dumps({"option_quote_enrichment_required": True}), encoding="utf-8")
    write_csv(repo / module.UNIVERSE_INPUT, ["ticker"], [{"ticker": "QQQ"}, {"ticker": "SPY"}])
    write_csv(repo / module.CONTRACT_INPUT, ["ticker"], [{"ticker": "QQQ"}, {"ticker": "SPY"}])


def run_stage(tmp_path: Path) -> tuple[Path, dict]:
    repo = tmp_path / "repo"
    seed_inputs(repo)
    payload = module.run(repo, execute=False)
    return repo, payload


def test_required_output_files_created_in_dry_run(tmp_path):
    repo, _ = run_stage(tmp_path)
    for filename in REQUIRED_FILES:
        assert (repo / module.OUT_REL / filename).exists()


def test_dry_run_summary_contract(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_option_quote_enrichment_summary.json").read_text(encoding="utf-8"))
    assert summary["final_status"] == "PASS_V22_032_R1_DRY_RUN_SCHEMA_READY"
    assert summary["final_decision"] == "OPTION_QUOTE_ENRICHMENT_READY_FOR_LIQUIDITY_AUDIT_RESEARCH_ONLY"
    assert summary["execution_mode"] == "DRY_RUN"
    assert summary["source_clean_contract_row_count"] > 0
    assert summary["quote_enrichment_attempted"] is False
    assert summary["moomoo_connection_attempted"] is False
    assert summary["market_data_fetch_allowed"] is False
    assert summary["moomoo_connection_allowed"] is False
    assert summary["option_quote_fetch_allowed"] is False
    assert summary["option_chain_fetch_allowed"] is False
    assert summary["trade_context_used"] is False
    assert summary["unlock_trade_called"] is False
    assert summary["place_order_called"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
    assert summary["trade_allowed"] is False


def test_risk_gate_trade_blocks(tmp_path):
    repo, _ = run_stage(tmp_path)
    gate = json.loads((repo / module.OUT_REL / "v22_option_quote_enrichment_risk_gate.json").read_text(encoding="utf-8"))
    assert gate["trade_context_allowed"] is False
    assert gate["unlock_trade_allowed"] is False
    assert gate["place_order_allowed"] is False


def test_field_coverage_contains_required_quote_fields(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_option_quote_enrichment_field_coverage_audit.csv")
    names = {row["field_name"] for row in rows}
    assert {"bid", "ask", "mid", "volume", "open_interest", "implied_volatility", "delta", "gamma", "theta", "vega"}.issubset(names)


def test_no_top_level_broker_network_or_process_imports():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    banned_modules = {"moomoo", "futu", "yfinance", "requests", "urllib", "http", "subprocess", "shutil", "os"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(banned_modules)


def test_forbidden_trade_api_strings_are_not_called():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    forbidden = {"unlock_trade", "place_order", "modify_order", "cancel_order"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                assert func.attr not in forbidden
            if isinstance(func, ast.Name):
                assert func.id not in forbidden


def test_module_writes_only_under_v22_032_r1_output_dir(tmp_path):
    repo, payload = run_stage(tmp_path)
    expected = (repo / module.OUT_REL).resolve()
    allowed_seed_files = {
        (repo / module.SOURCE_CLEAN_INPUT).resolve(),
        (repo / module.SOURCE_SUMMARY_INPUT).resolve(),
        (repo / module.V22_033_SUMMARY_INPUT).resolve(),
        (repo / module.UNIVERSE_INPUT).resolve(),
        (repo / module.CONTRACT_INPUT).resolve(),
    }
    assert payload["module_id"] == "V22.032_R1"
    for path in repo.rglob("*"):
        if path.is_file() and path.resolve() not in allowed_seed_files:
            assert expected in path.resolve().parents
