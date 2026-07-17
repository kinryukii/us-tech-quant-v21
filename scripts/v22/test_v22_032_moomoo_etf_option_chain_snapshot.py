from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_032_moomoo_etf_option_chain_snapshot.py")
SPEC = importlib.util.spec_from_file_location("v22_032", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


REQUIRED_FILES = [
    "v22_moomoo_etf_option_chain_snapshot_raw.csv",
    "v22_moomoo_etf_option_chain_snapshot_clean.csv",
    "v22_moomoo_etf_option_chain_underlying_audit.csv",
    "v22_moomoo_etf_option_chain_fetch_audit.csv",
    "v22_moomoo_etf_option_chain_field_coverage_audit.csv",
    "v22_moomoo_etf_option_chain_snapshot_summary.json",
    "v22_moomoo_etf_option_chain_snapshot_risk_gate.json",
    "V22.032_moomoo_etf_option_chain_snapshot_report.txt",
]

TICKERS = ["SMH", "SOXX", "QQQ", "SPY", "DIA", "SOXL", "TQQQ", "SPXL", "UDOW", "SOXS", "SQQQ", "SPXS", "SDOW"]


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
    universe_rows = []
    for ticker in TICKERS:
        group = "CORE_ETF"
        tier = "CORE"
        leveraged = False
        inverse = False
        multiple = 1
        if ticker in {"SOXL", "TQQQ", "SPXL", "UDOW"}:
            group = "SECONDARY_LEVERAGED_LONG"
            tier = "SECONDARY_HIGH_RISK"
            leveraged = True
            multiple = 3
        if ticker in {"SOXS", "SQQQ", "SPXS", "SDOW"}:
            group = "SECONDARY_LEVERAGED_INVERSE"
            tier = "SECONDARY_HIGH_RISK"
            leveraged = True
            inverse = True
            multiple = -3
        universe_rows.append(
            {
                "ticker": ticker,
                "theme_bucket": "SEMICONDUCTOR" if ticker in {"SMH", "SOXX", "SOXL", "SOXS"} else "INDEX",
                "universe_group": group,
                "universe_tier": tier,
                "leveraged_flag": leveraged,
                "inverse_flag": inverse,
                "leverage_multiple": multiple,
                "high_risk_secondary_flag": tier == "SECONDARY_HIGH_RISK",
            }
        )
    write_csv(repo / module.UNIVERSE_INPUT, ["ticker", "theme_bucket", "universe_group", "universe_tier", "leveraged_flag", "inverse_flag", "leverage_multiple", "high_risk_secondary_flag"], universe_rows)
    (repo / module.UNIVERSE_SUMMARY_INPUT).parent.mkdir(parents=True, exist_ok=True)
    (repo / module.UNIVERSE_SUMMARY_INPUT).write_text(json.dumps({"final_status": "PASS_V22_030_ETF_OPTION_UNIVERSE_REGISTRY_READY"}), encoding="utf-8")
    write_csv(repo / module.CONTRACT_INPUT, ["ticker"], [{"ticker": ticker} for ticker in TICKERS])
    (repo / module.CONTRACT_SUMMARY_INPUT).parent.mkdir(parents=True, exist_ok=True)
    (repo / module.CONTRACT_SUMMARY_INPUT).write_text(json.dumps({"final_status": "PASS_V22_031_ETF_OPTION_CONTRACT_SPEC_REGISTRY_READY"}), encoding="utf-8")


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
    summary = json.loads((repo / module.OUT_REL / "v22_moomoo_etf_option_chain_snapshot_summary.json").read_text(encoding="utf-8"))
    assert summary["final_status"] == "PASS_V22_032_DRY_RUN_SCHEMA_READY"
    assert summary["final_decision"] == "MOOMOO_ETF_OPTION_CHAIN_SNAPSHOT_READY_FOR_COVERAGE_AUDIT_RESEARCH_ONLY"
    assert summary["execution_mode"] == "DRY_RUN"
    assert summary["target_underlying_count"] == 13
    assert summary["raw_contract_row_count"] == 0
    assert summary["clean_contract_row_count"] == 0
    assert summary["moomoo_connection_attempted"] is False
    assert summary["option_chain_fetch_attempted"] is False
    assert summary["market_data_fetch_allowed"] is False
    assert summary["moomoo_connection_allowed"] is False
    assert summary["option_chain_fetch_allowed"] is False
    assert summary["trade_context_used"] is False
    assert summary["unlock_trade_called"] is False
    assert summary["place_order_called"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
    assert summary["trade_allowed"] is False


def test_risk_gate_trade_blocks(tmp_path):
    repo, _ = run_stage(tmp_path)
    gate = json.loads((repo / module.OUT_REL / "v22_moomoo_etf_option_chain_snapshot_risk_gate.json").read_text(encoding="utf-8"))
    assert gate["trade_context_allowed"] is False
    assert gate["unlock_trade_allowed"] is False
    assert gate["place_order_allowed"] is False


def test_underlying_and_field_coverage_audits(tmp_path):
    repo, _ = run_stage(tmp_path)
    underlyings = read_rows(repo / module.OUT_REL / "v22_moomoo_etf_option_chain_underlying_audit.csv")
    assert {row["underlying"] for row in underlyings} == set(TICKERS)
    fields = read_rows(repo / module.OUT_REL / "v22_moomoo_etf_option_chain_field_coverage_audit.csv")
    field_names = {row["field_name"] for row in fields}
    assert {"bid", "ask", "mid", "volume", "open_interest", "implied_volatility", "delta", "gamma", "theta", "vega"}.issubset(field_names)


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


def test_module_writes_only_under_v22_032_output_dir(tmp_path):
    repo, payload = run_stage(tmp_path)
    expected = (repo / module.OUT_REL).resolve()
    allowed_seed_files = {
        (repo / module.UNIVERSE_INPUT).resolve(),
        (repo / module.UNIVERSE_SUMMARY_INPUT).resolve(),
        (repo / module.CONTRACT_INPUT).resolve(),
        (repo / module.CONTRACT_SUMMARY_INPUT).resolve(),
    }
    assert payload["module_id"] == "V22.032"
    for path in repo.rglob("*"):
        if path.is_file() and path.resolve() not in allowed_seed_files:
            assert expected in path.resolve().parents
