from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_033_r1_option_chain_liquidity_and_coverage_audit_after_quote_enrichment.py")
SPEC = importlib.util.spec_from_file_location("v22_033_r1", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


REQUIRED_FILES = [
    "v22_option_chain_post_enrichment_liquidity_coverage_audit.csv",
    "v22_option_chain_post_enrichment_underlying_readiness_audit.csv",
    "v22_option_chain_post_enrichment_field_blocker_audit.csv",
    "v22_option_chain_post_enrichment_candidate_generation_gate.csv",
    "v22_option_chain_post_enrichment_liquidity_bucket_audit.csv",
    "v22_option_chain_post_enrichment_summary.json",
    "v22_option_chain_post_enrichment_risk_gate.json",
    "V22.033_R1_option_chain_liquidity_and_coverage_after_quote_enrichment_report.txt",
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
    clean_rows = []
    raw_rows = []
    for idx in range(4):
        row = {
            "enrichment_time_utc": "2026-07-05T16:01:45Z",
            "underlying": "QQQ",
            "universe_group": "CORE_ETF",
            "universe_tier": "CORE",
            "theme_bucket": "NASDAQ",
            "leveraged_flag": False,
            "inverse_flag": False,
            "expiration": "2026-07-10" if idx < 2 else "2026-07-17",
            "dte": "",
            "strike": str(500 + idx),
            "call_put": "CALL" if idx % 2 == 0 else "PUT",
            "option_code": f"US.QQQ260710C50{idx}000",
            "bid": "1.00" if idx != 1 else "0.00",
            "ask": "1.10",
            "mid": "1.05",
            "last": "1.08",
            "volume": "0" if idx == 0 else "10",
            "open_interest": "",
            "implied_volatility": "",
            "delta": "",
            "gamma": "",
            "theta": "",
            "vega": "",
            "spread_pct": "0.047619" if idx < 2 else "0.20",
        }
        clean_rows.append(row)
        raw_rows.append({**row, "bid_raw": row["bid"], "ask_raw": row["ask"]})
    fields = list(clean_rows[0].keys())
    write_csv(repo / module.CLEAN_INPUT, fields, clean_rows)
    write_csv(repo / module.RAW_INPUT, fields + ["bid_raw", "ask_raw"], raw_rows)
    write_csv(
        repo / module.UNDERLYING_AUDIT_INPUT,
        ["underlying", "theme_bucket", "universe_group", "universe_tier", "leveraged_flag", "inverse_flag", "high_risk_secondary_flag"],
        [{"underlying": "QQQ", "theme_bucket": "NASDAQ", "universe_group": "CORE_ETF", "universe_tier": "CORE", "leveraged_flag": False, "inverse_flag": False, "high_risk_secondary_flag": False}],
    )
    write_csv(repo / module.FIELD_COVERAGE_INPUT, ["field_name", "clean_non_null_count", "clean_coverage_ratio"], [])
    (repo / module.SUMMARY_INPUT).parent.mkdir(parents=True, exist_ok=True)
    (repo / module.SUMMARY_INPUT).write_text(
        json.dumps(
            {
                "execution_mode": "EXECUTE_READ_ONLY",
                "target_contract_count": 500,
                "enriched_raw_row_count": 4,
                "enriched_clean_row_count": 4,
                "quote_enrichment_succeeded": True,
            }
        ),
        encoding="utf-8",
    )
    (repo / module.V22_033_SUMMARY_INPUT).parent.mkdir(parents=True, exist_ok=True)
    (repo / module.V22_033_SUMMARY_INPUT).write_text(json.dumps({"option_quote_enrichment_required": True}), encoding="utf-8")
    write_csv(repo / module.UNIVERSE_INPUT, ["ticker", "theme_bucket", "universe_group", "universe_tier", "leveraged_flag", "inverse_flag", "high_risk_secondary_flag"], [{"ticker": "QQQ", "theme_bucket": "NASDAQ", "universe_group": "CORE_ETF", "universe_tier": "CORE", "leveraged_flag": False, "inverse_flag": False, "high_risk_secondary_flag": False}])
    write_csv(repo / module.CONTRACT_INPUT, ["ticker"], [{"ticker": "QQQ"}])


def run_stage(tmp_path: Path) -> tuple[Path, dict]:
    repo = tmp_path / "repo"
    seed_inputs(repo)
    payload = module.run(repo)
    return repo, payload


def test_required_output_files_are_created(tmp_path):
    repo, _ = run_stage(tmp_path)
    for filename in REQUIRED_FILES:
        assert (repo / module.OUT_REL / filename).exists()


def test_summary_post_enrichment_warning_contract(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_option_chain_post_enrichment_summary.json").read_text(encoding="utf-8"))
    assert summary["final_decision"] == "OPTION_CHAIN_POST_ENRICHMENT_LIQUIDITY_COVERAGE_READY_RESEARCH_ONLY"
    assert summary["v22_032_r1_summary_input_exists"] is True
    assert summary["v22_032_r1_clean_input_exists"] is True
    assert summary["source_execution_mode"] in {"EXECUTE_READ_ONLY", "DRY_RUN"}
    assert summary["enriched_clean_row_count"] == 4
    assert summary["total_valid_bid_ask_count"] > 0
    assert summary["total_valid_volume_count"] > 0
    assert summary["total_valid_iv_count"] == 0
    assert summary["total_valid_greeks_count"] == 0
    assert summary["total_valid_open_interest_count"] == 0
    assert summary["final_status"] == "WARN_V22_033_R1_QUOTES_READY_BUT_IV_GREEKS_OI_MISSING"
    assert summary["underlying_ready_for_candidate_generation_count"] == 0
    assert summary["candidate_generation_allowed_count"] == 0
    assert summary["iv_greeks_enrichment_required"] is True
    assert summary["open_interest_enrichment_required"] is True


def test_field_blockers_and_candidate_generation_gates(tmp_path):
    repo, _ = run_stage(tmp_path)
    blockers = read_rows(repo / module.OUT_REL / "v22_option_chain_post_enrichment_field_blocker_audit.csv")
    blocker_fields = {row["field_name"] for row in blockers if row["blocker_triggered"] == "True"}
    assert {"open_interest", "implied_volatility", "delta", "gamma", "theta", "vega"}.issubset(blocker_fields)
    gates = read_rows(repo / module.OUT_REL / "v22_option_chain_post_enrichment_candidate_generation_gate.csv")
    gate_names = {row["gate_name"] for row in gates}
    assert {"BID_ASK_GATE", "SPREAD_GATE", "VOLUME_GATE", "OPEN_INTEREST_GATE", "IV_GATE", "GREEKS_GATE", "NO_BROKER_ACTION_GATE", "NO_TRADE_GATE"}.issubset(gate_names)
    by_gate = {row["gate_name"]: row for row in gates}
    assert by_gate["BID_ASK_GATE"]["gate_passed"] == "True"
    assert by_gate["OPEN_INTEREST_GATE"]["gate_passed"] == "False"
    assert by_gate["IV_GATE"]["gate_passed"] == "False"
    assert by_gate["GREEKS_GATE"]["gate_passed"] == "False"


def test_summary_and_risk_gates_are_false(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_option_chain_post_enrichment_summary.json").read_text(encoding="utf-8"))
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
        "option_quote_fetch_allowed",
        "daily_chain_execution_allowed",
        "factor_promotion_allowed",
        "factor_weight_change_allowed",
    ]:
        assert summary[key] is False
    assert summary["protected_outputs_modified"] is False
    risk_gate = json.loads((repo / module.OUT_REL / "v22_option_chain_post_enrichment_risk_gate.json").read_text(encoding="utf-8"))
    assert risk_gate["candidate_generation_allowed"] is False


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
    forbidden_calls = {"system", "unlock_trade", "place_order", "modify_order", "cancel_order", "query_broker_account"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                assert func.attr not in forbidden_calls
            if isinstance(func, ast.Name):
                assert func.id not in forbidden_calls


def test_module_writes_only_under_v22_033_r1_output_dir(tmp_path):
    repo, payload = run_stage(tmp_path)
    expected = (repo / module.OUT_REL).resolve()
    allowed_seed_files = {
        (repo / module.RAW_INPUT).resolve(),
        (repo / module.CLEAN_INPUT).resolve(),
        (repo / module.UNDERLYING_AUDIT_INPUT).resolve(),
        (repo / module.FIELD_COVERAGE_INPUT).resolve(),
        (repo / module.SUMMARY_INPUT).resolve(),
        (repo / module.V22_033_SUMMARY_INPUT).resolve(),
        (repo / module.UNIVERSE_INPUT).resolve(),
        (repo / module.CONTRACT_INPUT).resolve(),
    }
    assert payload["module_id"] == "V22.033_R1"
    for path in repo.rglob("*"):
        if path.is_file() and path.resolve() not in allowed_seed_files:
            assert expected in path.resolve().parents


def test_no_output_rows_allow_broker_adoption_or_trade(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_option_chain_post_enrichment_liquidity_coverage_audit.csv")
    assert rows
    for row in rows:
        assert row["broker_action_allowed"] == "False"
        assert row["official_adoption_allowed"] == "False"
        assert row["trade_allowed"] == "False"
