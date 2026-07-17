from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_041_option_intraday_etf_only_research_layer_r1.py")
SPEC = importlib.util.spec_from_file_location("v22_041", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


REQUIRED_FILES = [
    "etf_option_contract_universe.csv",
    "etf_option_quote_audit.csv",
    "etf_option_liquidity_candidates.csv",
    "etf_option_rejected_contracts.csv",
    "v22_041_summary.json",
    "V22.041_etf_option_intraday_research_report.txt",
]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def run_stage(tmp_path: Path):
    repo = tmp_path / "repo"
    payload = module.run(repo)
    return repo, payload


def test_required_outputs_created(tmp_path):
    repo, _ = run_stage(tmp_path)
    for filename in REQUIRED_FILES:
        assert (repo / module.OUT_REL / filename).exists()


def test_etf_only_whitelist_enforcement(tmp_path):
    repo, summary = run_stage(tmp_path)
    universe = read_rows(repo / module.OUT_REL / "etf_option_contract_universe.csv")
    allowed = set(module.ALLOWED_ETFS)
    for row in universe:
        if row["underlying"] in allowed:
            assert row["asset_scope"] == "ETF_OPTION"
        else:
            assert row["asset_scope"] == "BLOCKED_SINGLE_STOCK_OR_NON_ETF_OPTION"
    assert summary["etf_only_gate_passed"] is True


def test_single_stock_contracts_are_blocked(tmp_path):
    repo, summary = run_stage(tmp_path)
    rejected = read_rows(repo / module.OUT_REL / "etf_option_rejected_contracts.csv")
    single_stock = [row for row in rejected if row["underlying"] == "AAPL"]
    assert single_stock
    assert single_stock[0]["single_stock_blocked"] == "True"
    assert "UNDERLYING_NOT_IN_ETF_WHITELIST" in single_stock[0]["reject_reason"]
    assert summary["single_stock_contract_count"] == 1
    assert summary["single_stock_blocked_count"] == 1


def test_zero_bid_contracts_are_rejected(tmp_path):
    repo, summary = run_stage(tmp_path)
    rejected = read_rows(repo / module.OUT_REL / "etf_option_rejected_contracts.csv")
    assert any("ZERO_OR_NEGATIVE_BID" in row["reject_reason"] for row in rejected)
    assert summary["zero_bid_count"] >= 1


def test_ask_less_than_or_equal_bid_contracts_are_rejected(tmp_path):
    repo, _ = run_stage(tmp_path)
    rejected = read_rows(repo / module.OUT_REL / "etf_option_rejected_contracts.csv")
    assert any("ASK_NOT_GREATER_THAN_BID" in row["reject_reason"] for row in rejected)


def test_wide_spread_contracts_are_rejected(tmp_path):
    repo, summary = run_stage(tmp_path)
    rejected = read_rows(repo / module.OUT_REL / "etf_option_rejected_contracts.csv")
    assert any("WIDE_SPREAD" in row["reject_reason"] for row in rejected)
    assert summary["wide_spread_count"] >= 1


def test_missing_iv_greeks_and_oi_are_warnings_not_failures(tmp_path):
    repo, summary = run_stage(tmp_path)
    audit = read_rows(repo / module.OUT_REL / "etf_option_quote_audit.csv")
    assert summary["final_status"] == module.PASS_STATUS
    assert summary["missing_iv_count"] >= 1
    assert summary["missing_greeks_count"] >= 1
    assert summary["missing_open_interest_count"] >= 1
    assert any(row["audit_status"] == "WARN_OPTIONAL_FIELDS_MISSING" for row in audit)


def test_broker_and_adoption_gates_are_always_false(tmp_path):
    repo, summary = run_stage(tmp_path)
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
    for filename in ["etf_option_contract_universe.csv", "etf_option_liquidity_candidates.csv", "etf_option_rejected_contracts.csv"]:
        for row in read_rows(repo / module.OUT_REL / filename):
            assert row["broker_action_allowed"] == "False"
            assert row["official_adoption_allowed"] == "False"


def test_no_trade_context_or_order_behavior_exists():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    forbidden_names = {"OpenSecTradeContext", "unlock_trade", "place_order", "modify_order", "cancel_order"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                assert func.attr not in forbidden_names
            if isinstance(func, ast.Name):
                assert func.id not in forbidden_names
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert "OpenSecTradeContext" not in text


def test_output_schema_stability(tmp_path):
    repo, _ = run_stage(tmp_path)
    expected = {
        "etf_option_contract_universe.csv": module.UNIVERSE_FIELDS,
        "etf_option_quote_audit.csv": module.QUOTE_AUDIT_FIELDS,
        "etf_option_liquidity_candidates.csv": module.CANDIDATE_FIELDS,
        "etf_option_rejected_contracts.csv": module.REJECT_FIELDS,
    }
    for filename, fields in expected.items():
        with (repo / module.OUT_REL / filename).open(encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            assert next(reader) == fields


def test_final_status_and_decision_are_deterministic(tmp_path):
    _, first = run_stage(tmp_path / "a")
    _, second = run_stage(tmp_path / "b")
    for payload in [first, second]:
        assert payload["final_status"] == module.PASS_STATUS
        assert payload["final_decision"] == module.READY_DECISION
        assert payload["execution_mode"] == "PLAN"


def test_module_writes_only_under_v22_041_output_dir(tmp_path):
    repo, payload = run_stage(tmp_path)
    expected = (repo / module.OUT_REL).resolve()
    assert payload["module_id"] == "V22.041"
    for path in repo.rglob("*"):
        if path.is_file():
            assert expected in path.resolve().parents
