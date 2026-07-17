from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_033_option_chain_liquidity_and_coverage_audit.py")
SPEC = importlib.util.spec_from_file_location("v22_033", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


REQUIRED_FILES = [
    "v22_option_chain_liquidity_coverage_audit.csv",
    "v22_option_chain_underlying_readiness_audit.csv",
    "v22_option_chain_field_blocker_audit.csv",
    "v22_option_chain_candidate_generation_gate.csv",
    "v22_option_chain_liquidity_coverage_summary.json",
    "v22_option_chain_liquidity_coverage_risk_gate.json",
    "V22.033_option_chain_liquidity_and_coverage_audit_report.txt",
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
    raw_rows = []
    clean_rows = []
    underlying_rows = []
    for ticker in TICKERS:
        group = "CORE_ETF"
        tier = "CORE"
        leveraged = False
        inverse = False
        high_risk = False
        if ticker in {"SOXL", "TQQQ", "SPXL", "UDOW"}:
            group = "SECONDARY_LEVERAGED_LONG"
            tier = "SECONDARY_HIGH_RISK"
            leveraged = True
            high_risk = True
        if ticker in {"SOXS", "SQQQ", "SPXS", "SDOW"}:
            group = "SECONDARY_LEVERAGED_INVERSE"
            tier = "SECONDARY_HIGH_RISK"
            leveraged = True
            inverse = True
            high_risk = True
        universe_rows.append({"ticker": ticker, "theme_bucket": "INDEX", "universe_group": group, "universe_tier": tier, "leveraged_flag": leveraged, "inverse_flag": inverse, "high_risk_secondary_flag": high_risk})
        if ticker in {"SMH", "QQQ"}:
            row = {
                "snapshot_time_utc": "2026-07-06T00:00:00Z",
                "underlying": ticker,
                "universe_group": group,
                "universe_tier": tier,
                "theme_bucket": "INDEX",
                "leveraged_flag": leveraged,
                "inverse_flag": inverse,
                "leverage_multiple": 1,
                "expiration": "2026-07-10",
                "dte": "",
                "strike": "100",
                "call_put": "CALL",
                "option_code": f"US.{ticker}260710C100000",
                "bid": "",
                "ask": "",
                "mid": "",
                "volume": "",
                "open_interest": "",
                "implied_volatility": "",
                "delta": "",
                "gamma": "",
                "theta": "",
                "vega": "",
                "spread_pct": "",
            }
            raw_rows.append(row)
            clean_rows.append(row)
        underlying_rows.append({"underlying": ticker, "theme_bucket": "INDEX", "universe_group": group, "universe_tier": tier, "leveraged_flag": leveraged, "inverse_flag": inverse, "high_risk_secondary_flag": high_risk})
    snapshot_fields = [
        "snapshot_time_utc",
        "underlying",
        "universe_group",
        "universe_tier",
        "theme_bucket",
        "leveraged_flag",
        "inverse_flag",
        "leverage_multiple",
        "expiration",
        "dte",
        "strike",
        "call_put",
        "option_code",
        "bid",
        "ask",
        "mid",
        "volume",
        "open_interest",
        "implied_volatility",
        "delta",
        "gamma",
        "theta",
        "vega",
        "spread_pct",
    ]
    write_csv(repo / module.RAW_INPUT, snapshot_fields, raw_rows)
    write_csv(repo / module.CLEAN_INPUT, snapshot_fields, clean_rows)
    write_csv(repo / module.UNDERLYING_AUDIT_INPUT, ["underlying", "theme_bucket", "universe_group", "universe_tier", "leveraged_flag", "inverse_flag", "high_risk_secondary_flag"], underlying_rows)
    field_rows = []
    for field in snapshot_fields:
        count = 2 if field in {"snapshot_time_utc", "underlying", "expiration", "strike", "call_put", "option_code"} else 0
        field_rows.append({"field_name": field, "clean_non_null_count": count, "clean_coverage_ratio": 1.0 if count else 0})
    write_csv(repo / module.FIELD_COVERAGE_INPUT, ["field_name", "clean_non_null_count", "clean_coverage_ratio"], field_rows)
    (repo / module.SUMMARY_INPUT).parent.mkdir(parents=True, exist_ok=True)
    (repo / module.SUMMARY_INPUT).write_text(json.dumps({"execution_mode": "EXECUTE_READ_ONLY", "raw_contract_row_count": 2, "clean_contract_row_count": 2, "target_underlying_count": 13}), encoding="utf-8")
    write_csv(repo / module.UNIVERSE_INPUT, ["ticker", "theme_bucket", "universe_group", "universe_tier", "leveraged_flag", "inverse_flag", "high_risk_secondary_flag"], universe_rows)
    write_csv(repo / module.CONTRACT_INPUT, ["ticker"], [{"ticker": ticker} for ticker in TICKERS])


def run_stage(tmp_path: Path) -> tuple[Path, dict]:
    repo = tmp_path / "repo"
    seed_inputs(repo)
    payload = module.run(repo)
    return repo, payload


def test_required_output_files_are_created(tmp_path):
    repo, _ = run_stage(tmp_path)
    for filename in REQUIRED_FILES:
        assert (repo / module.OUT_REL / filename).exists()


def test_summary_structure_only_status_and_counts(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_option_chain_liquidity_coverage_summary.json").read_text(encoding="utf-8"))
    assert summary["final_decision"] == "OPTION_CHAIN_LIQUIDITY_COVERAGE_READY_RESEARCH_ONLY"
    assert summary["v22_032_summary_input_exists"] is True
    assert summary["v22_032_clean_input_exists"] is True
    assert summary["source_execution_mode"] == "EXECUTE_READ_ONLY"
    assert summary["clean_contract_row_count"] == 2
    assert summary["total_valid_bid_ask_count"] == 0
    assert summary["final_status"] == "WARN_V22_033_OPTION_CHAIN_STRUCTURE_ONLY_QUOTES_MISSING"
    assert summary["underlying_ready_for_candidate_generation_count"] == 0
    assert summary["candidate_generation_allowed_count"] == 0
    assert summary["option_quote_enrichment_required"] is True


def test_field_blockers_and_candidate_gates(tmp_path):
    repo, _ = run_stage(tmp_path)
    blockers = read_rows(repo / module.OUT_REL / "v22_option_chain_field_blocker_audit.csv")
    blocker_fields = {row["field_name"] for row in blockers if row["blocker_triggered"] == "True"}
    assert {"bid", "ask", "mid", "spread_pct", "volume", "open_interest", "implied_volatility", "delta", "gamma", "theta", "vega"}.issubset(blocker_fields)
    gates = read_rows(repo / module.OUT_REL / "v22_option_chain_candidate_generation_gate.csv")
    gate_names = {row["gate_name"] for row in gates}
    assert {"BID_ASK_GATE", "SPREAD_GATE", "IV_GATE", "GREEKS_GATE", "VOLUME_OI_GATE", "NO_BROKER_ACTION_GATE", "NO_TRADE_GATE"}.issubset(gate_names)


def test_summary_gates_are_false(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_option_chain_liquidity_coverage_summary.json").read_text(encoding="utf-8"))
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


def test_module_writes_only_under_v22_033_output_dir(tmp_path):
    repo, payload = run_stage(tmp_path)
    expected = (repo / module.OUT_REL).resolve()
    allowed_seed_files = {
        (repo / module.RAW_INPUT).resolve(),
        (repo / module.CLEAN_INPUT).resolve(),
        (repo / module.UNDERLYING_AUDIT_INPUT).resolve(),
        (repo / module.FIELD_COVERAGE_INPUT).resolve(),
        (repo / module.SUMMARY_INPUT).resolve(),
        (repo / module.UNIVERSE_INPUT).resolve(),
        (repo / module.CONTRACT_INPUT).resolve(),
    }
    assert payload["module_id"] == "V22.033"
    for path in repo.rglob("*"):
        if path.is_file() and path.resolve() not in allowed_seed_files:
            assert expected in path.resolve().parents


def test_no_output_rows_allow_broker_adoption_or_trade(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_option_chain_liquidity_coverage_audit.csv")
    assert rows
    for row in rows:
        assert row["broker_action_allowed"] == "False"
        assert row["official_adoption_allowed"] == "False"
        assert row["trade_allowed"] == "False"
