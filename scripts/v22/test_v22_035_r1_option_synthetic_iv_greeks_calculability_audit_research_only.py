from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).with_name("v22_035_r1_option_synthetic_iv_greeks_calculability_audit_research_only.py")
SPEC = importlib.util.spec_from_file_location("v22_035_r1", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def seed_repo(repo: Path, *, spot: str = "550", dte: str = "", valuation: str = "2026-07-06T00:00:00Z", expiration: str = "2026-07-17") -> list[Path]:
    rows = [
        {
            "option_code": "US.QQQ260717C500000",
            "underlying": "QQQ",
            "expiration": expiration,
            "strike": "500",
            "call_put": "CALL",
            "bid": "1.00",
            "ask": "1.10",
            "mid": "1.05",
            "volume": "10",
            "underlying_price": spot,
            "enrichment_time_utc": valuation,
            "dte": dte,
        }
    ]
    path = repo / module.V22_032_R1_READ_ONLY_DIR / "v22_option_quote_enrichment_clean.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False, lineterminator="\n")
    summary = repo / module.V22_034_R1_DIR / "v22_034_r1_summary.json"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text('{"final_status":"WARN"}\n', encoding="utf-8")
    return [path, summary]


def test_normalize_column_name_handles_noise():
    assert module.normalize_column_name(" Option.Code (Raw)//X ") == "option_code_raw_x"
    assert module.normalize_column_name("Best--Bid") == "best_bid"
    assert module.normalize_column_name("Greek__Delta") == "greek_delta"


def test_alias_resolution_maps_required_fields():
    columns = ["contract_symbol", "root_symbol", "expiry", "strike-price", "right", "best_bid", "best_ask", "mark_price", "trade_volume", "spot.price", "quote_timestamp", "days_to_expiry"]
    resolved = module.resolve_alias_columns(columns)
    for target in ["option_code", "underlying_symbol", "expiration", "strike", "option_type", "bid", "ask", "mid", "volume", "underlying_spot", "valuation_date", "dte"]:
        assert resolved[target]


def test_option_type_parser_normalizes_call_and_put():
    assert module.parse_option_type("call") == "CALL"
    assert module.parse_option_type("C") == "CALL"
    assert module.parse_option_type("PUT") == "PUT"
    assert module.parse_option_type("p") == "PUT"
    assert module.parse_option_type("bad") == ""


def test_dte_uses_source_when_valid():
    dte, status = module.compute_audit_dte("7", "2026-07-17", "2026-07-06")
    assert dte == 7
    assert status == "DTE_USABLE_FROM_SOURCE"


def test_dte_computed_from_expiration_and_valuation_date():
    dte, status = module.compute_audit_dte("", "2026-07-17", "2026-07-06")
    assert dte == 11
    assert status == "DTE_COMPUTED_FROM_EXPIRATION_AND_VALUATION_DATE"


def test_zero_or_expired_contracts_invalid():
    assert module.compute_audit_dte("0", "2026-07-06", "2026-07-06")[1] == "DTE_INVALID_OR_EXPIRED"
    assert module.compute_audit_dte("", "2026-07-05", "2026-07-06")[1] == "DTE_INVALID_OR_EXPIRED"


def test_synthetic_calculable_requires_all_core_inputs(tmp_path):
    repo = tmp_path / "repo"
    seed_repo(repo)
    summary = module.run(repo)
    assert summary["synthetic_iv_calculable_count"] == 1
    assert summary["synthetic_greeks_calculable_after_iv_count"] == 1
    assert summary["full_option_candidate_generation_allowed"] is False


def test_missing_spot_blocks_synthetic_but_allows_liquidity(tmp_path):
    repo = tmp_path / "repo"
    seed_repo(repo, spot="")
    summary = module.run(repo)
    assert summary["synthetic_iv_calculable_count"] == 0
    assert summary["synthetic_greeks_calculable_after_iv_count"] == 0
    assert summary["liquidity_only_research_screen_allowed"] is True
    assert summary["full_option_candidate_generation_allowed"] is False


def test_safety_gates_are_always_false(tmp_path):
    repo = tmp_path / "repo"
    seed_repo(repo)
    summary = module.run(repo)
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
    assert summary["trade_order_allowed"] is False
    policy = pd.read_csv(repo / module.OUT_REL / "option_synthetic_candidate_generation_safety_policy.csv")
    assert policy.loc[0, "full_option_candidate_generation_allowed"] == False


def test_missing_input_returns_fail_and_exit_code_one(tmp_path):
    repo = tmp_path / "repo"
    summary = module.run(repo)
    assert summary["final_status"] == "FAIL_V22_035_R1_INPUT_NOT_FOUND"
    assert module.main(["--repo-root", str(repo)]) == 1


def test_pass_or_warn_returns_exit_code_zero(tmp_path):
    repo = tmp_path / "repo"
    seed_repo(repo)
    assert module.main(["--repo-root", str(repo)]) == 0


def test_existing_artifacts_are_not_mutated(tmp_path):
    repo = tmp_path / "repo"
    files = seed_repo(repo)
    before = {path: path.read_bytes() for path in files}
    module.run(repo)
    after = {path: path.read_bytes() for path in files}
    assert before == after
