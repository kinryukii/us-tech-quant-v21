from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).with_name("v22_036_r2_option_underlying_spot_freshness_root_cause_and_same_snapshot_recovery_audit_research_only.py")
SPEC = importlib.util.spec_from_file_location("v22_036_r2", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def seed_contract(repo: Path) -> Path:
    path = repo / module.V22_032_R1_READ_ONLY_DIR / "v22_option_quote_enrichment_clean.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"option_code": "US.QQQ260717C500000", "underlying": "QQQ", "expiration": "2026-07-17", "strike": "500", "call_put": "CALL", "bid": "1.0", "ask": "1.1", "mid": "1.05", "volume": "10", "enrichment_time_utc": "2026-07-05T16:00:00Z", "dte": ""}]).to_csv(path, index=False, lineterminator="\n")
    summary = repo / module.V22_032_R1_READ_ONLY_DIR / "v22_option_quote_enrichment_summary.json"
    summary.write_text(json.dumps({"underlying_attempted_count": 1, "underlying_enriched_count": 1}), encoding="utf-8")
    return path


def seed_r1_rejection(repo: Path, stale: bool = True) -> None:
    root = repo / module.V22_036_R1_DIR
    root.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"source_category": "LOCAL_MOOMOO_PRICE_CACHE", "source_file": "cache.csv", "underlying_symbol": "QQQ", "candidate_spot_price": "712.6", "candidate_price_column": "close", "candidate_date_column": "date", "candidate_timestamp_column": "", "latest_observed_date": "2026-07-02", "latest_observed_timestamp": "", "source_status": "CANDIDATE_USABLE"}]).to_csv(root / "option_underlying_spot_source_discovery_audit.csv", index=False)
    pd.DataFrame([{"underlying_symbol": "QQQ", "option_valuation_date": "2026-07-05", "option_quote_timestamp": "2026-07-05T16:00:00", "underlying_price_date": "2026-07-02", "underlying_quote_timestamp": "", "date_diff_days": "3", "alignment_status": "STALE_UNDERLYING_PRICE"}]).to_csv(root / "option_underlying_spot_timestamp_alignment_audit.csv", index=False)
    pd.DataFrame([{"underlying_symbol": "QQQ", "selection_status": "REJECTED_STALE_SPOT"}]).to_csv(root / "option_underlying_spot_selection_audit.csv", index=False)


def seed_spot_csv(repo: Path, date: str = "2026-07-05", price: object = 712.6) -> Path:
    path = repo / module.V22_032_R1_READ_ONLY_DIR / "underlying_quote.csv"
    pd.DataFrame([{"ticker": "QQQ", "timestamp": f"{date}T16:00:00Z", "last_price": price}]).to_csv(path, index=False)
    return path


def test_normalize_column_name_handles_noise():
    assert module.normalize_column_name(" Last.Price (USD)//X ") == "last_price_usd_x"
    assert module.normalize_column_name("UNDERLYING--SPOT") == "underlying_spot"


def test_normalize_symbol_maps_common_forms():
    for raw in ["QQQ", "QQQ.US", "US.QQQ", "NASDAQ.QQQ", "QQQ NASDAQ"]:
        assert module.normalize_symbol(raw) == "QQQ"


def test_timestamp_parser_formats():
    for raw in ["2026-07-05", "2026/07/05", "20260705", "2026-07-05T16:00:00Z", "2026-07-05T16:00:00+09:00"]:
        assert module.parse_date_or_timestamp(raw)[0] is not None


def test_trace_detects_summary_and_underlying_csv(tmp_path):
    repo = tmp_path / "repo"
    seed_contract(repo)
    seed_spot_csv(repo)
    trace = module.trace_v22_032_underlying_enrichment(repo)
    assert trace["contains_underlying_enriched_count"].any()
    assert (trace["trace_status"] == "UNDERLYING_QUOTE_ROW_FOUND").any()


def test_rejection_root_cause_stale_and_date_parse():
    root, repair = module.classify_rejection_root_cause({"source_status": "CANDIDATE_USABLE"}, {"alignment_status": "STALE_UNDERLYING_PRICE"}, {"selection_status": "REJECTED_STALE_SPOT"})
    assert root == "STALE_PRICE_TRUE_REJECTION"
    assert repair == "NOT_REPAIRABLE_STALE_SOURCE"
    root2, repair2 = module.classify_rejection_root_cause({"source_status": "CANDIDATE_DATE_NON_NUMERIC"}, {"alignment_status": "parse_failed"}, {})
    assert root2 == "DATE_PARSE_FAILURE"
    assert repair2 == "REPAIRABLE_BY_TIMESTAMP_NORMALIZATION"


def test_extract_candidates_from_csv_and_json_rejects_bad_prices(tmp_path):
    repo = tmp_path / "repo"
    csv_path = repo / "spot.csv"
    repo.mkdir()
    pd.DataFrame([{"ticker": "QQQ", "date": "2026-07-05", "last_price": "712.6"}, {"ticker": "QQQ", "date": "2026-07-05", "last_price": "0"}, {"ticker": "QQQ", "date": "2026-07-05", "last_price": "-1"}, {"ticker": "QQQ", "date": "2026-07-05", "last_price": "bad"}]).to_csv(csv_path, index=False)
    rows = module.extract_candidates_from_csv(csv_path, "QQQ", "2026-07-05", "2026-07-05T16:00:00")
    statuses = {r["candidate_status"] for r in rows}
    assert "SAME_DATE_CANDIDATE_USABLE" in statuses
    assert "PRICE_INVALID_REJECTED" in statuses
    json_path = repo / "spot.json"
    json_path.write_text(json.dumps({"outer": {"ticker": "QQQ", "timestamp": "2026-07-05T16:00:00Z", "last_price": 700}}), encoding="utf-8")
    assert module.extract_candidates_from_json(json_path, "QQQ", "2026-07-05", "2026-07-05T16:00:00")


def test_recovery_selects_same_snapshot_over_stale():
    candidates = pd.DataFrame([
        {"source_version": "LOCAL", "source_file": "stale.csv", "candidate_record_path": "$", "normalized_candidate_symbol": "QQQ", "candidate_status": "STALE_CANDIDATE_REJECTED", "candidate_price": 1, "candidate_date": "2026-07-01", "candidate_timestamp": ""},
        {"source_version": "V22.032_R1", "source_file": "same.json", "candidate_record_path": "$", "normalized_candidate_symbol": "QQQ", "candidate_status": "SAME_SNAPSHOT_CANDIDATE_USABLE", "candidate_price": 2, "candidate_date": "2026-07-05", "candidate_timestamp": "2026-07-05T16:00:00"},
    ])
    sel = module.select_same_snapshot_recovery(candidates, "QQQ")
    assert sel.iloc[0]["recovered_source_file"] == "same.json"


def test_stale_only_sets_refresh_needed(tmp_path):
    repo = tmp_path / "repo"
    seed_contract(repo)
    seed_r1_rejection(repo)
    seed_spot_csv(repo, date="2026-07-01")
    summary = module.run(repo)
    assert summary["read_only_underlying_quote_refresh_needed"] is True
    assert summary["synthetic_iv_solver_next_step_allowed"] is False


def test_recovered_injection_and_calculability_and_no_mutation(tmp_path):
    repo = tmp_path / "repo"
    contract = seed_contract(repo)
    spot = seed_spot_csv(repo)
    before = {p: p.read_bytes() for p in [contract, spot]}
    summary = module.run(repo)
    assert {p: p.read_bytes() for p in [contract, spot]} == before
    assert summary["recovered_spot_injected_contract_count"] == 1
    assert summary["synthetic_iv_calculable_after_recovery_count"] == 1
    assert summary["synthetic_iv_solver_next_step_allowed"] is True
    injected = pd.read_csv(repo / module.OUT_REL / "option_contract_rows_with_recovered_underlying_spot_injected_research_only.csv")
    assert "recovered_underlying_spot" in injected.columns


def test_safety_gates_false(tmp_path):
    repo = tmp_path / "repo"
    seed_contract(repo)
    seed_spot_csv(repo)
    summary = module.run(repo)
    assert summary["full_option_candidate_generation_allowed"] is False
    assert summary["provider_oi_ready"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
    assert summary["trade_order_allowed"] is False


def test_missing_input_exit_one_and_warn_pass_exit_zero(tmp_path):
    empty = tmp_path / "empty"
    assert module.run(empty)["final_status"] == "FAIL_V22_036_R2_INPUT_NOT_FOUND"
    assert module.main(["--repo-root", str(empty)]) == 1
    repo = tmp_path / "repo"
    seed_contract(repo)
    assert module.main(["--repo-root", str(repo)]) == 0
