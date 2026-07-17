from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_041_r3_live_option_quote_enrichment_from_chain_codes.py")
SPEC = importlib.util.spec_from_file_location("v22_041_r3", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


REQUIRED_FILES = [
    "live_option_chain_metadata.csv",
    "live_option_enrichment_targets.csv",
    "live_option_quote_enriched_rows.csv",
    "live_option_quote_enrichment_batch_audit.csv",
    "live_option_quote_field_mapping_audit.csv",
    "live_option_liquidity_candidates_after_enrichment.csv",
    "live_option_rejected_after_enrichment.csv",
    "v22_041_r3_summary.json",
    "V22.041_R3_live_option_quote_enrichment_from_chain_codes_report.txt",
]


def chain_row(code: str = "US.QQQ260717C500000", underlying: str = "QQQ", expiration: str = "2026-07-17", strike: float = 500.0, option_type: str = "CALL"):
    return {
        "code": code,
        "underlying": underlying,
        "strike_time": expiration,
        "strike_price": strike,
        "option_type": option_type,
    }


def quote_row(code: str = "US.QQQ260717C500000", bid: float = 1.0, ask: float = 1.1, volume: int | None = 10):
    row = {
        "code": code,
        "bid_price": bid,
        "ask_price": ask,
        "last_price": 1.05,
        "open_interest": 100,
        "implied_volatility": 0.2,
        "delta": 0.4,
        "gamma": 0.01,
        "theta": -0.02,
        "vega": 0.1,
        "quote_time": "2026-07-08T14:00:00Z",
    }
    if volume is not None:
        row["volume"] = volume
    return row


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_chain_metadata_to_enrichment_target_selection():
    rows = [
        chain_row(code="US.QQQ_A", strike=400, option_type="CALL"),
        chain_row(code="US.QQQ_B", strike=500, option_type="PUT"),
        chain_row(code="US.QQQ_C", strike=600, option_type="CALL"),
    ]
    metadata = module.metadata_from_chain_rows(rows)
    targets = module.select_enrichment_targets(metadata, max_contracts=2, spot_by_underlying={"QQQ": 505.0})
    assert len(targets) == 2
    assert {row["call_put"] for row in targets} == {"CALL", "PUT"}
    assert all(row["selection_reason"] == "NEAR_THE_MONEY_BY_UNDERLYING_SPOT" for row in targets)


def test_dte_filtering_excludes_out_of_range_and_zero_dte():
    rows = [
        chain_row(code="US.QQQ_OK", expiration="2026-07-17"),
        chain_row(code="US.QQQ_FAR", expiration="2026-09-30"),
        chain_row(code="US.QQQ_ZERO", expiration="2026-07-08"),
    ]
    targets = module.select_enrichment_targets(module.metadata_from_chain_rows(rows), max_contracts=10, include_zero_dte=False)
    assert [row["option_code"] for row in targets] == ["US.QQQ_OK"]
    targets_zero = module.select_enrichment_targets(module.metadata_from_chain_rows(rows), max_contracts=10, include_zero_dte=True)
    assert "US.QQQ_ZERO" in {row["option_code"] for row in targets_zero}


def test_max_contracts_cap():
    rows = [chain_row(code=f"US.QQQ_{i}", strike=400 + i) for i in range(20)]
    targets = module.select_enrichment_targets(module.metadata_from_chain_rows(rows), max_contracts=5)
    assert len(targets) == 5


def test_batch_size_batching():
    assert [len(batch) for batch in module.chunks(list(range(10)), 4)] == [4, 4, 2]


def test_quote_field_name_normalization():
    meta = module.metadata_from_chain_rows([chain_row()])[0]
    enriched = module.normalize_quote_row(meta, quote_row(), "QUOTE_FETCHED_READ_ONLY")
    assert enriched["bid"] == 1.0
    assert enriched["ask"] == 1.1
    assert enriched["volume"] == 10
    assert enriched["_mapped_fields"]["bid"] == "bid_price"
    assert enriched["_mapped_fields"]["ask"] == "ask_price"


def test_bid_ask_mid_spread_calculation():
    meta = module.metadata_from_chain_rows([chain_row()])[0]
    enriched = module.normalize_quote_row(meta, quote_row(bid=2.0, ask=2.2), "QUOTE_FETCHED_READ_ONLY")
    assert enriched["mid"] == 2.1
    assert round(enriched["spread"], 6) == 0.2
    assert round(enriched["spread_pct"], 6) == round(0.2 / 2.1, 6)


def test_missing_volume_field_is_warning_not_hard_failure(tmp_path):
    summary = module.run(tmp_path / "repo", injected_chain_rows=[chain_row()], injected_quote_rows=[quote_row(volume=None)])
    assert summary["volume_field_mapped"] is False
    assert summary["liquidity_candidate_count"] == 1
    enriched = read_rows(tmp_path / "repo" / module.OUT_REL / "live_option_quote_enriched_rows.csv")
    assert "volume" in enriched[0]["warning_fields"]


def test_missing_iv_greeks_oi_are_warnings_not_hard_failures(tmp_path):
    quote = {"code": "US.QQQ260717C500000", "bid_price": 1.0, "ask_price": 1.1, "volume": 10}
    summary = module.run(tmp_path / "repo", injected_chain_rows=[chain_row()], injected_quote_rows=[quote])
    assert summary["open_interest_field_mapped"] is False
    assert summary["iv_field_mapped"] is False
    assert summary["greeks_field_mapped"] is False
    assert summary["liquidity_candidate_count"] == 1


def test_liquidity_candidate_filter_after_enrichment(tmp_path):
    chain = [chain_row(code="US.QQQ_GOOD"), chain_row(code="US.QQQ_WIDE", strike=501)]
    quotes = [quote_row(code="US.QQQ_GOOD", bid=1, ask=1.1), quote_row(code="US.QQQ_WIDE", bid=1, ask=2)]
    summary = module.run(tmp_path / "repo", injected_chain_rows=chain, injected_quote_rows=quotes)
    assert summary["liquidity_candidate_count"] == 1
    rejects = read_rows(tmp_path / "repo" / module.OUT_REL / "live_option_rejected_after_enrichment.csv")
    assert any("WIDE_SPREAD" in row["reject_reason"] for row in rejects)


def test_zero_candidates_after_enrichment_classified_correctly(tmp_path):
    summary = module.run(tmp_path / "repo", injected_chain_rows=[chain_row()], injected_quote_rows=[quote_row(bid=1, ask=2)])
    assert summary["final_status"] == module.WARN_ZERO_STATUS
    assert summary["final_decision"] == module.ZERO_DECISION
    assert summary["quote_enrichment_root_cause_if_zero"] == "QUOTE_ENRICHED_ZERO_LIQUIDITY_CANDIDATES"


def test_no_fallback_local_rows_by_default(tmp_path):
    summary = module.run(tmp_path / "repo", execute=False)
    assert summary["fallback_rows_used"] is False
    assert summary["total_raw_contract_count"] == 0


def test_broker_action_allowed_remains_false(tmp_path):
    summary = module.run(tmp_path / "repo", injected_chain_rows=[chain_row()], injected_quote_rows=[quote_row()])
    assert summary["broker_action_allowed"] is False


def test_official_adoption_allowed_remains_false(tmp_path):
    summary = module.run(tmp_path / "repo", injected_chain_rows=[chain_row()], injected_quote_rows=[quote_row()])
    assert summary["official_adoption_allowed"] is False


def test_trade_context_unlock_and_place_order_flags_remain_false(tmp_path):
    summary = module.run(tmp_path / "repo", injected_chain_rows=[chain_row()], injected_quote_rows=[quote_row()])
    assert summary["trade_context_used"] is False
    assert summary["unlock_trade_called"] is False
    assert summary["place_order_called"] is False


def test_summary_schema_stability(tmp_path):
    repo = tmp_path / "repo"
    summary = module.run(repo, injected_chain_rows=[chain_row()], injected_quote_rows=[quote_row()])
    payload = json.loads((repo / module.OUT_REL / "v22_041_r3_summary.json").read_text(encoding="utf-8"))
    for field in module.SUMMARY_FIELDS:
        assert field in summary
        assert field in payload
    for filename in REQUIRED_FILES:
        assert (repo / module.OUT_REL / filename).exists()


def test_output_csv_schema_stability(tmp_path):
    repo = tmp_path / "repo"
    module.run(repo, injected_chain_rows=[chain_row()], injected_quote_rows=[quote_row()])
    expected = {
        "live_option_chain_metadata.csv": module.METADATA_FIELDS,
        "live_option_enrichment_targets.csv": module.TARGET_FIELDS,
        "live_option_quote_enriched_rows.csv": module.ENRICHED_FIELDS,
        "live_option_quote_enrichment_batch_audit.csv": module.BATCH_FIELDS,
        "live_option_quote_field_mapping_audit.csv": module.FIELD_AUDIT_FIELDS,
        "live_option_liquidity_candidates_after_enrichment.csv": module.CANDIDATE_FIELDS,
        "live_option_rejected_after_enrichment.csv": module.REJECT_FIELDS,
    }
    for filename, fields in expected.items():
        with (repo / module.OUT_REL / filename).open(encoding="utf-8", newline="") as handle:
            assert next(csv.reader(handle)) == fields


def test_deterministic_final_status_and_decision(tmp_path):
    first = module.run(tmp_path / "a", injected_chain_rows=[chain_row()], injected_quote_rows=[quote_row()])
    second = module.run(tmp_path / "b", injected_chain_rows=[chain_row()], injected_quote_rows=[quote_row()])
    assert first["final_status"] == second["final_status"] == module.PASS_STATUS
    assert first["final_decision"] == second["final_decision"] == module.READY_DECISION


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
