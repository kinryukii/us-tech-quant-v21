from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_000_v22_charter_scope_and_risk_policy_freeze.py")
SPEC = importlib.util.spec_from_file_location("v22_000", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


REQUIRED_FILES = [
    "v22_charter_scope_freeze.json",
    "v22_module_roadmap.csv",
    "v22_allowed_blocked_strategy_registry.csv",
    "v22_etf_universe_scope_registry.csv",
    "v22_risk_policy_freeze.json",
    "V22.000_v22_charter_scope_and_risk_policy_freeze_report.txt",
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


def test_final_status_and_decision_exact(tmp_path):
    repo, payload = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_charter_scope_freeze.json").read_text(encoding="utf-8"))
    assert payload["final_status"] == "PASS_V22_000_CHARTER_SCOPE_AND_RISK_POLICY_FROZEN"
    assert payload["final_decision"] == "V22_READY_FOR_CONSOLIDATION_FACTOR_VALIDITY_AND_ETF_OPTION_RESEARCH_ONLY"
    assert summary["final_status"] == "PASS_V22_000_CHARTER_SCOPE_AND_RISK_POLICY_FROZEN"
    assert summary["final_decision"] == "V22_READY_FOR_CONSOLIDATION_FACTOR_VALIDITY_AND_ETF_OPTION_RESEARCH_ONLY"


def test_broker_adoption_trade_and_option_fetch_gates_false(tmp_path):
    _, payload = run_stage(tmp_path)
    for key in [
        "broker_action_allowed",
        "official_adoption_allowed",
        "trade_allowed",
        "moomoo_connection_allowed",
        "option_chain_fetch_allowed",
    ]:
        assert payload[key] is False


def test_long_call_and_long_put_allowed(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_allowed_blocked_strategy_registry.csv")
    by_name = {row["strategy_name"]: row for row in rows}
    assert by_name["LONG_CALL"]["permission_status"] == "ALLOWED_INITIAL_RESEARCH_ONLY"
    assert by_name["LONG_PUT"]["permission_status"] == "ALLOWED_INITIAL_RESEARCH_ONLY"
    assert by_name["LONG_CALL"]["initial_phase_allowed"] == "True"
    assert by_name["LONG_PUT"]["initial_phase_allowed"] == "True"


def test_naked_short_call_and_put_blocked(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_allowed_blocked_strategy_registry.csv")
    by_name = {row["strategy_name"]: row for row in rows}
    assert by_name["NAKED_SHORT_CALL"]["permission_status"] == "BLOCKED"
    assert by_name["NAKED_SHORT_PUT"]["permission_status"] == "BLOCKED"
    assert by_name["NAKED_SHORT_CALL"]["naked_short_exposure_allowed"] == "False"
    assert by_name["NAKED_SHORT_PUT"]["naked_short_exposure_allowed"] == "False"


def test_spy_included_and_spx_ndx_excluded(tmp_path):
    repo, payload = run_stage(tmp_path)
    assert "SPY" in payload["core_etf_universe"]
    assert "SPX" in payload["excluded_cash_settled_index_options"]
    assert "NDX" in payload["excluded_cash_settled_index_options"]
    rows = read_rows(repo / module.OUT_REL / "v22_etf_universe_scope_registry.csv")
    by_ticker = {row["ticker"]: row for row in rows}
    assert by_ticker["SPY"]["universe_tier"] == "CORE_ETF"
    assert by_ticker["SPX"]["universe_tier"] == "EXCLUDED_CASH_SETTLED_INDEX_OPTION"
    assert by_ticker["NDX"]["universe_tier"] == "EXCLUDED_CASH_SETTLED_INDEX_OPTION"


def test_leveraged_etfs_marked_secondary_high_risk(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_etf_universe_scope_registry.csv")
    by_ticker = {row["ticker"]: row for row in rows}
    for ticker in ["SOXL", "TQQQ", "SPXL", "UDOW"]:
        assert by_ticker[ticker]["leveraged_flag"] == "True"
        assert "SECONDARY" in by_ticker[ticker]["universe_tier"]
        assert "HIGH_RISK" in by_ticker[ticker]["universe_tier"]


def test_module_has_no_broker_or_network_imports():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    banned_roots = {"moomoo", "futu", "yfinance", "requests", "urllib"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(banned_roots)


def test_output_path_under_v22_000_only(tmp_path):
    repo, payload = run_stage(tmp_path)
    expected = (repo / module.OUT_REL).resolve()
    assert Path(payload["output_dir"]).resolve() == expected
    assert expected.name == "V22.000_V22_CHARTER_SCOPE_AND_RISK_POLICY_FREEZE"
    for path in (repo / "outputs").rglob("*"):
        if path.is_file():
            assert expected in path.resolve().parents


def test_risk_policy_freeze_fields(tmp_path):
    repo, _ = run_stage(tmp_path)
    policy = json.loads((repo / module.OUT_REL / "v22_risk_policy_freeze.json").read_text(encoding="utf-8"))
    assert policy["max_open_strategy_packages_default"] == 1
    assert policy["single_long_call_allowed"] is True
    assert policy["single_long_put_allowed"] is True
    assert policy["debit_spread_allowed"] is True
    assert policy["naked_short_allowed"] is False
    assert policy["uncovered_short_allowed"] is False
    assert policy["short_premium_0dte_allowed"] is False
    assert policy["manual_execution_only"] is True
    assert policy["paper_plan_only"] is True
    assert policy["option_stop_loss_pct_reference"] == -30
    assert policy["confirmation_order"] == ["1h", "15m", "1m"]
