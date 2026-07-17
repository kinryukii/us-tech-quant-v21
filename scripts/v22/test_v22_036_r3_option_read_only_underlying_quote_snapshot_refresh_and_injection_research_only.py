from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).with_name("v22_036_r3_option_read_only_underlying_quote_snapshot_refresh_and_injection_research_only.py")
SPEC = importlib.util.spec_from_file_location("v22_036_r3", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def seed_contract(repo: Path) -> Path:
    path = repo / module.V22_032_R1_READ_ONLY_DIR / "v22_option_quote_enrichment_clean.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"option_code": "US.QQQ260717C500000", "underlying": "QQQ", "expiration": "2026-07-17", "strike": "500", "call_put": "CALL", "bid": "1.0", "ask": "1.1", "mid": "1.05", "volume": "10", "enrichment_time_utc": "2026-07-05T16:00:00", "dte": ""}]).to_csv(path, index=False, lineterminator="\n")
    return path


def provider_audit_from_frame(frame: pd.DataFrame):
    meta = {"provider": "MOOMOO", "requested_underlying_symbol": "QQQ", "provider_symbol_used": "US.QQQ", "provider_call_attempted": True, "provider_call_succeeded": True, "provider_return_code": "0", "provider_return_message": "", "provider_row_count": len(frame), "quote_refresh_status": "", "quote_refresh_error": "", "read_only_quote_context_used": True}
    return module.extract_provider_quote_fields(frame, meta, module.parse_date_or_timestamp("2026-07-05T16:30:00"))


def test_normalize_column_name_handles_noise():
    assert module.normalize_column_name(" Last.Price (USD)//X ") == "last_price_usd_x"
    assert module.normalize_column_name("UNDERLYING--SPOT") == "underlying_spot"


def test_normalize_symbol_maps_common_forms():
    for raw in ["QQQ", "QQQ.US", "US.QQQ", "NASDAQ.QQQ"]:
        assert module.normalize_symbol(raw) == "QQQ"


def test_refresh_permission_gate_pass_and_failures():
    assert module.build_refresh_permission_gate("QQQ")["gate_status"] == "PASS_READ_ONLY_UNDERLYING_QUOTE_REFRESH_SCOPE"
    assert module.build_refresh_permission_gate("SPY")["gate_status"] == "FAIL_UNDERLYING_SYMBOL_NOT_ALLOWED"
    assert module.build_refresh_permission_gate("QQQ", trade_context_allowed=True)["gate_status"] == "FAIL_FORBIDDEN_CONTEXT_REQUESTED"


def test_contract_discovery_selects_contract_over_summary(tmp_path):
    repo = tmp_path / "repo"
    contract = seed_contract(repo)
    summary = repo / module.V22_036_R2_DIR / "summary.csv"
    summary.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"underlying": "QQQ", "count": 1}]).to_csv(summary, index=False)
    candidates = module.discover_contract_input_files(repo)
    _frame, _aliases, source, _audit = module.select_contract_input(candidates)
    assert source == str(contract)


def test_provider_quote_field_extraction_aliases():
    frame = pd.DataFrame([{"last_price": "700", "bid": "699", "ask": "701", "mid": "700", "quote_timestamp": "2026-07-05T16:30:00"}])
    audit, _raw = provider_audit_from_frame(frame)
    assert audit["refreshed_last_price"] == 700
    assert audit["refreshed_bid"] == 699
    assert audit["refreshed_ask"] == 701
    assert audit["refreshed_mid"] == 700
    assert audit["quote_refresh_status"] == "REFRESHED_UNDERLYING_QUOTE_USABLE"


def test_clean_snapshot_prefers_last_and_falls_back_to_midpoint():
    audit, _raw = provider_audit_from_frame(pd.DataFrame([{"last_price": "700", "bid": "699", "ask": "701", "quote_timestamp": "2026-07-05T16:30:00"}]))
    clean = module.clean_underlying_quote_snapshot(audit, module.parse_date_or_timestamp("2026-07-05T16:30:00"))
    assert clean["selected_underlying_spot"] == 700
    audit2, _raw2 = provider_audit_from_frame(pd.DataFrame([{"bid": "699", "ask": "701", "quote_timestamp": "2026-07-05T16:30:00"}]))
    clean2 = module.clean_underlying_quote_snapshot(audit2, module.parse_date_or_timestamp("2026-07-05T16:30:00"))
    assert clean2["selected_underlying_spot"] == 700


def test_clean_snapshot_rejects_bad_prices():
    for value in ["0", "-1", "bad", ""]:
        audit, _raw = provider_audit_from_frame(pd.DataFrame([{"last_price": value, "quote_timestamp": "2026-07-05T16:30:00"}]))
        clean = module.clean_underlying_quote_snapshot(audit, module.parse_date_or_timestamp("2026-07-05T16:30:00"))
        assert clean["price_valid"] is False


def test_timestamp_alignment_same_date_after_and_stale(tmp_path):
    repo = tmp_path / "repo"
    seed_contract(repo)
    frame, aliases, _src, _audit = module.select_contract_input(module.discover_contract_input_files(repo))
    clean = {"quote_date": "2026-07-05", "quote_timestamp": "2026-07-05T16:30:00", "refresh_timestamp_local": "2026-07-05T16:30:00"}
    assert module.audit_timestamp_alignment("QQQ", frame, aliases, clean)["alignment_status"] == "REFRESHED_AFTER_OPTION_SNAPSHOT_RESEARCH_ONLY"
    clean["quote_date"] = "2026-07-02"
    clean["quote_timestamp"] = "2026-07-02T16:30:00"
    assert module.audit_timestamp_alignment("QQQ", frame, aliases, clean)["alignment_status"] == "STALE_OR_MISMATCHED_REFRESH_REJECTED"


def test_spot_injection_and_calculability_no_mutation(tmp_path):
    repo = tmp_path / "repo"
    contract = seed_contract(repo)
    before = contract.read_bytes()
    frame, aliases, _src, _audit = module.select_contract_input(module.discover_contract_input_files(repo))
    clean = {"normalized_underlying_symbol": "QQQ", "selected_underlying_spot": 700, "selected_price_source_field": "last_price", "quote_date": "2026-07-05", "quote_timestamp": "2026-07-05T16:30:00", "refresh_timestamp_local": "2026-07-05T16:30:00", "price_valid": True}
    align = module.audit_timestamp_alignment("QQQ", frame, aliases, clean)
    injected = module.inject_refreshed_underlying_spot(frame, aliases, clean, align)
    calc = module.refresh_synthetic_calculability_after_injection(injected, aliases)
    assert contract.read_bytes() == before
    assert injected["refreshed_underlying_spot_injected"].iloc[0] == True
    assert calc["synthetic_iv_calculable_after_refreshed_spot_injection"].iloc[0] == True


def test_safety_policy_gates_false():
    calc = pd.DataFrame([{"has_valid_market_price": True, "volume": "10", "has_valid_underlying_spot_after_refresh": True, "synthetic_iv_calculable_after_refreshed_spot_injection": True}])
    policy = module.build_safety_policy(calc)
    assert policy["synthetic_iv_solver_next_step_allowed"] is True
    assert policy["full_option_candidate_generation_allowed"] is False
    assert policy["broker_action_allowed"] is False
    assert policy["official_adoption_allowed"] is False
    assert policy["trade_order_allowed"] is False


def test_trade_flags_always_false_in_dry_run(tmp_path):
    repo = tmp_path / "repo"
    seed_contract(repo)
    summary = module.run(repo, execute=False)
    assert summary["trade_context_used"] is False
    assert summary["unlock_trade_called"] is False
    assert summary["place_order_called"] is False


def test_missing_input_and_scope_violation_exit_one(tmp_path):
    empty = tmp_path / "empty"
    assert module.run(empty)["final_status"] == "FAIL_V22_036_R3_INPUT_NOT_FOUND"
    assert module.main(["--repo-root", str(empty)]) == 1
    repo = tmp_path / "repo"
    seed_contract(repo)
    assert module.run(repo, requested_underlying_symbol="SPY")["final_status"] == "FAIL_V22_036_R3_SCOPE_VIOLATION"
    assert module.main(["--repo-root", str(repo), "--underlying", "SPY"]) == 1


def test_warn_status_exit_zero_and_inputs_not_mutated(tmp_path):
    repo = tmp_path / "repo"
    contract = seed_contract(repo)
    before = contract.read_bytes()
    assert module.main(["--repo-root", str(repo)]) == 0
    assert contract.read_bytes() == before
