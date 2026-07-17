from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_031_etf_option_contract_spec_registry.py")
SPEC = importlib.util.spec_from_file_location("v22_031", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


REQUIRED_FILES = [
    "v22_etf_option_contract_spec_registry.csv",
    "v22_etf_option_contract_risk_registry.csv",
    "v22_etf_option_contract_strategy_scope.csv",
    "v22_etf_option_contract_spec_group_summary.csv",
    "v22_etf_option_contract_spec_summary.json",
    "v22_etf_option_contract_spec_risk_gate.json",
    "V22.031_etf_option_contract_spec_registry_report.txt",
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


def seed_v22_030(repo: Path) -> None:
    rows = [
        ("SMH", "SEMICONDUCTOR", "CORE_ETF", "CORE", False, False, 1),
        ("SOXX", "SEMICONDUCTOR", "CORE_ETF", "CORE", False, False, 1),
        ("QQQ", "NASDAQ", "CORE_ETF", "CORE", False, False, 1),
        ("SPY", "SP500", "CORE_ETF", "CORE", False, False, 1),
        ("DIA", "DOW", "CORE_ETF", "CORE", False, False, 1),
        ("SOXL", "SEMICONDUCTOR", "SECONDARY_LEVERAGED_LONG", "SECONDARY_HIGH_RISK", True, False, 3),
        ("TQQQ", "NASDAQ", "SECONDARY_LEVERAGED_LONG", "SECONDARY_HIGH_RISK", True, False, 3),
        ("SPXL", "SP500", "SECONDARY_LEVERAGED_LONG", "SECONDARY_HIGH_RISK", True, False, 3),
        ("UDOW", "DOW", "SECONDARY_LEVERAGED_LONG", "SECONDARY_HIGH_RISK", True, False, 3),
        ("SOXS", "SEMICONDUCTOR", "SECONDARY_LEVERAGED_INVERSE", "SECONDARY_HIGH_RISK", True, True, -3),
        ("SQQQ", "NASDAQ", "SECONDARY_LEVERAGED_INVERSE", "SECONDARY_HIGH_RISK", True, True, -3),
        ("SPXS", "SP500", "SECONDARY_LEVERAGED_INVERSE", "SECONDARY_HIGH_RISK", True, True, -3),
        ("SDOW", "DOW", "SECONDARY_LEVERAGED_INVERSE", "SECONDARY_HIGH_RISK", True, True, -3),
    ]
    write_csv(
        repo / module.UNIVERSE_INPUT,
        ["ticker", "theme_bucket", "universe_group", "universe_tier", "leveraged_flag", "inverse_flag", "leverage_multiple", "high_risk_secondary_flag"],
        [
            {
                "ticker": ticker,
                "theme_bucket": theme,
                "universe_group": group,
                "universe_tier": tier,
                "leveraged_flag": leveraged,
                "inverse_flag": inverse,
                "leverage_multiple": multiple,
                "high_risk_secondary_flag": tier == "SECONDARY_HIGH_RISK",
            }
            for ticker, theme, group, tier, leveraged, inverse, multiple in rows
        ],
    )
    (repo / module.UNIVERSE_SUMMARY_INPUT).parent.mkdir(parents=True, exist_ok=True)
    (repo / module.UNIVERSE_SUMMARY_INPUT).write_text(json.dumps({"final_status": "PASS_V22_030_ETF_OPTION_UNIVERSE_REGISTRY_READY"}), encoding="utf-8")


def run_stage(tmp_path: Path) -> tuple[Path, dict]:
    repo = tmp_path / "repo"
    seed_v22_030(repo)
    payload = module.run(repo)
    return repo, payload


def test_required_output_files_are_created(tmp_path):
    repo, _ = run_stage(tmp_path)
    for filename in REQUIRED_FILES:
        assert (repo / module.OUT_REL / filename).exists()


def test_summary_status_inputs_and_counts(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_etf_option_contract_spec_summary.json").read_text(encoding="utf-8"))
    assert summary["final_status"] == "PASS_V22_031_ETF_OPTION_CONTRACT_SPEC_REGISTRY_READY"
    assert summary["final_decision"] == "ETF_OPTION_CONTRACT_SPEC_REGISTRY_READY_RESEARCH_ONLY"
    assert summary["v22_030_universe_input_exists"] is True
    assert summary["v22_030_summary_input_exists"] is True
    assert summary["contract_spec_row_count"] == 13
    assert summary["standard_100_share_contract_count"] == 13
    assert summary["american_style_assumption_count"] == 13
    assert summary["physical_delivery_assumption_count"] == 13
    assert summary["cash_settled_index_option_count"] == 0
    assert summary["live_option_chain_verified_count"] == 0
    assert summary["option_chain_fetch_allowed_count"] == 0


def test_contract_specs_tickers_and_risk_flags(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_etf_option_contract_spec_registry.csv")
    by_ticker = {row["ticker"]: row for row in rows}
    assert {"SMH", "SOXX", "QQQ", "SPY", "DIA", "SOXL", "TQQQ", "SPXL", "UDOW", "SOXS", "SQQQ", "SPXS", "SDOW"} == set(by_ticker)
    for ticker in ["SOXS", "SQQQ", "SPXS", "SDOW"]:
        assert by_ticker[ticker]["inverse_flag"] == "True"
        assert by_ticker[ticker]["requires_inverse_exposure_review"] == "True"
    for ticker in ["SOXL", "TQQQ", "SPXL", "UDOW"]:
        assert by_ticker[ticker]["leveraged_flag"] == "True"
        assert by_ticker[ticker]["high_risk_secondary_flag"] == "True"


def test_strategy_scope_permissions(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_etf_option_contract_strategy_scope.csv")
    by_strategy = {}
    for row in rows:
        by_strategy.setdefault(row["strategy_name"], set()).add(row["permission_status"])
    for strategy in ["LONG_CALL", "LONG_PUT", "DEBIT_CALL_SPREAD", "DEBIT_PUT_SPREAD"]:
        assert by_strategy[strategy] == {"ALLOWED_INITIAL_RESEARCH"}
    for strategy in ["NAKED_SHORT_CALL", "NAKED_SHORT_PUT"]:
        assert by_strategy[strategy] == {"BLOCKED"}


def test_summary_gates_are_false(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_etf_option_contract_spec_summary.json").read_text(encoding="utf-8"))
    assert summary["broker_action_allowed_count"] == 0
    assert summary["official_adoption_allowed_count"] == 0
    assert summary["trade_allowed_count"] == 0
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


def test_module_writes_only_under_v22_031_output_dir(tmp_path):
    repo, payload = run_stage(tmp_path)
    expected = (repo / module.OUT_REL).resolve()
    allowed_seed_files = {
        (repo / module.UNIVERSE_INPUT).resolve(),
        (repo / module.UNIVERSE_SUMMARY_INPUT).resolve(),
    }
    assert payload["module_id"] == "V22.031"
    for path in repo.rglob("*"):
        if path.is_file() and path.resolve() not in allowed_seed_files:
            assert expected in path.resolve().parents


def test_no_contract_spec_row_allows_broker_adoption_or_trade(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_etf_option_contract_spec_registry.csv")
    assert rows
    for row in rows:
        assert row["broker_action_allowed"] == "False"
        assert row["official_adoption_allowed"] == "False"
        assert row["trade_allowed"] == "False"
