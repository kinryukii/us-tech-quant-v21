from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).with_name("v22_036_r1_option_underlying_spot_source_resolution_and_injection_audit_research_only.py")
SPEC = importlib.util.spec_from_file_location("v22_036_r1", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def write_contract(repo: Path, symbols: list[str] | None = None) -> Path:
    symbols = symbols or ["QQQ"]
    rows = []
    for symbol in symbols:
        rows.append({"option_code": f"US.{symbol}260717C500000", "underlying": symbol, "expiration": "2026-07-17", "strike": "500", "call_put": "CALL", "bid": "1.0", "ask": "1.1", "mid": "1.05", "volume": "10", "enrichment_time_utc": "2026-07-05T16:00:00Z", "dte": ""})
    path = repo / module.V22_032_R1_READ_ONLY_DIR / "v22_option_quote_enrichment_clean.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False, lineterminator="\n")
    return path


def write_spot(repo: Path, symbol: str = "QQQ", date: str = "2026-07-05", price: object = 712.6, category_dir: Path | None = None) -> Path:
    root = category_dir or (repo / module.V22_032_R1_READ_ONLY_DIR)
    path = root / f"{symbol}_underlying_quote.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"ticker": symbol, "date": date, "close": price, "timestamp": f"{date}T20:00:00Z"}]).to_csv(path, index=False, lineterminator="\n")
    return path


def test_normalize_column_name_handles_noise():
    assert module.normalize_column_name(" Last.Price (USD)//X ") == "last_price_usd_x"
    assert module.normalize_column_name("UNDERLYING--SPOT") == "underlying_spot"


def test_alias_resolution_maps_spot_date_timestamp_and_symbol():
    cols = ["underlying_last", "last_price", "close", "price_date", "quote_timestamp", "underlying_symbol"]
    resolved = module.resolve_alias_columns(cols, include_spot=True)
    assert resolved["underlying_spot"] in {"underlying_last", "last_price", "close"}
    assert resolved["price_date"]
    assert resolved["underlying_symbol"]


def test_contract_discovery_selects_contract_table_over_summary(tmp_path):
    repo = tmp_path / "repo"
    contract = write_contract(repo)
    summary = repo / module.V22_035_R1_DIR / "summary.csv"
    summary.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"underlying": "QQQ", "count": 1}]).to_csv(summary, index=False)
    candidates = module.discover_contract_input_files(repo)
    assert candidates[0]["path"] == contract


def test_underlying_symbol_resolution_single_and_multiple(tmp_path):
    repo = tmp_path / "repo"
    write_contract(repo)
    candidates = module.discover_contract_input_files(repo)
    single = module.resolve_underlying_symbols(candidates[0]["frame"], candidates[0]["aliases"], "x.csv")
    assert single.iloc[0]["resolution_status"] == "RESOLVED_SINGLE_UNDERLYING"
    repo2 = tmp_path / "repo2"
    write_contract(repo2, ["QQQ", "SPY"])
    candidates2 = module.discover_contract_input_files(repo2)
    multi = module.resolve_underlying_symbols(candidates2[0]["frame"], candidates2[0]["aliases"], "x.csv")
    assert set(multi["resolution_status"]) == {"RESOLVED_MULTIPLE_UNDERLYINGS"}


def test_candidate_spot_source_extraction_rejects_bad_prices(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    bad_paths = []
    for idx, price in enumerate(["", "abc", 0, -1]):
        path = repo / f"bad{idx}.csv"
        pd.DataFrame([{"ticker": "QQQ", "date": "2026-07-05", "close": price}]).to_csv(path, index=False)
        bad_paths.append(("LOCAL_OTHER_PRICE_CACHE", path))
    audit = module.extract_candidate_spot_sources(bad_paths, ["QQQ"])
    assert {"CANDIDATE_PRICE_MISSING", "CANDIDATE_PRICE_NON_NUMERIC", "CANDIDATE_PRICE_NON_POSITIVE"}.issubset(set(audit["source_status"]))


def test_timestamp_alignment_same_day_one_day_and_stale():
    sources = pd.DataFrame([
        {"source_status": "CANDIDATE_USABLE", "underlying_symbol": "QQQ", "normalized_underlying_symbol": "QQQ", "latest_observed_date": "2026-07-05", "latest_observed_timestamp": "2026-07-05T20:00:00", "source_priority": 1},
        {"source_status": "CANDIDATE_USABLE", "underlying_symbol": "QQQ", "normalized_underlying_symbol": "QQQ", "latest_observed_date": "2026-07-04", "latest_observed_timestamp": "2026-07-04T20:00:00", "source_priority": 2},
        {"source_status": "CANDIDATE_USABLE", "underlying_symbol": "QQQ", "normalized_underlying_symbol": "QQQ", "latest_observed_date": "2026-07-02", "latest_observed_timestamp": "2026-07-02T20:00:00", "source_priority": 3},
    ])
    audit = module.audit_timestamp_alignment(sources, {"QQQ": {"date": "2026-07-05", "timestamp": "2026-07-05T16:00:00"}})
    assert {"SAME_DATE_ALIGNED", "DATE_WITHIN_ONE_DAY_ACCEPTED_RESEARCH_ONLY", "STALE_UNDERLYING_PRICE"}.issubset(set(audit["alignment_status"]))


def test_best_selection_prefers_same_date_v22_quote_over_cache(tmp_path):
    sources = pd.DataFrame([
        {"source_category": "LOCAL_MOOMOO_PRICE_CACHE", "source_file": "cache.csv", "normalized_underlying_symbol": "QQQ", "underlying_symbol": "QQQ", "candidate_spot_price": 1, "candidate_price_column": "close", "candidate_date_column": "date", "candidate_timestamp_column": "", "latest_observed_date": "2026-07-05", "latest_observed_timestamp": "", "source_priority": 3, "source_status": "CANDIDATE_USABLE"},
        {"source_category": "V22_032_UNDERLYING_QUOTE_ARTIFACT", "source_file": "quote.csv", "normalized_underlying_symbol": "QQQ", "underlying_symbol": "QQQ", "candidate_spot_price": 2, "candidate_price_column": "close", "candidate_date_column": "date", "candidate_timestamp_column": "", "latest_observed_date": "2026-07-05", "latest_observed_timestamp": "", "source_priority": 1, "source_status": "CANDIDATE_USABLE"},
    ])
    align = module.audit_timestamp_alignment(sources, {"QQQ": {"date": "2026-07-05", "timestamp": ""}})
    sel = module.select_best_spot_source(sources, align, ["QQQ"])
    assert sel.iloc[0]["selected_source_file"] == "quote.csv"


def test_spot_injection_new_copy_and_calculability_after_injection(tmp_path):
    repo = tmp_path / "repo"
    input_path = write_contract(repo)
    write_spot(repo)
    before = input_path.read_bytes()
    summary = module.run(repo)
    assert input_path.read_bytes() == before
    assert summary["injected_contract_row_count"] == 1
    assert summary["synthetic_iv_calculable_after_spot_injection_count"] == 1
    assert summary["synthetic_iv_calculation_allowed_next_step"] is True
    injected = pd.read_csv(repo / module.OUT_REL / "option_contract_rows_with_underlying_spot_injected_research_only.csv")
    assert "injected_underlying_spot" in injected.columns


def test_safety_gates_always_false(tmp_path):
    repo = tmp_path / "repo"
    write_contract(repo)
    write_spot(repo)
    summary = module.run(repo)
    assert summary["full_option_candidate_generation_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
    assert summary["trade_order_allowed"] is False
    assert summary["provider_oi_ready"] is False


def test_missing_input_returns_fail_and_exit_one(tmp_path):
    repo = tmp_path / "repo"
    assert module.run(repo)["final_status"] == "FAIL_V22_036_R1_INPUT_NOT_FOUND"
    assert module.main(["--repo-root", str(repo)]) == 1


def test_warn_or_pass_exit_zero_and_inputs_not_mutated(tmp_path):
    repo = tmp_path / "repo"
    contract = write_contract(repo)
    spot = write_spot(repo, date="2026-07-02")
    before = {p: p.read_bytes() for p in [contract, spot]}
    assert module.main(["--repo-root", str(repo)]) == 0
    after = {p: p.read_bytes() for p in [contract, spot]}
    assert before == after
