from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_041_r2_live_option_chain_coverage_and_zero_candidate_diagnostic.py")
SPEC = importlib.util.spec_from_file_location("v22_041_r2", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


REQUIRED_FILES = [
    "live_option_chain_coverage_by_underlying.csv",
    "live_option_field_availability_audit.csv",
    "live_option_filter_funnel.csv",
    "live_option_zero_candidate_root_cause.csv",
    "live_option_relaxed_filter_simulation.csv",
    "v22_041_r2_summary.json",
    "V22.041_R2_live_option_chain_coverage_and_zero_candidate_diagnostic_report.txt",
]


def base_row(**updates):
    row = {
        "underlying": "QQQ",
        "code": "US.QQQ260717C500000",
        "expiration": "2026-07-17",
        "strike": 500,
        "call_put": "CALL",
        "bid": 1.0,
        "ask": 1.1,
        "volume": 10,
    }
    row.update(updates)
    return row


def roots_for(rows):
    enriched = module.enrich_rows(rows)
    coverage = module.build_coverage_from_rows(rows)
    fields = module.field_availability(enriched)
    funnel = module.build_funnel(enriched)
    return module.classify_root_causes(enriched, coverage, fields, funnel)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_chain_empty_root_cause_classification():
    roots = roots_for([])
    assert roots[0]["root_cause_code"] == "CHAIN_EMPTY_OR_UNAVAILABLE"


def test_dte_filter_root_cause_classification():
    roots = roots_for([base_row(expiration="2026-09-30")])
    assert roots[0]["root_cause_code"] == "DTE_FILTER_ELIMINATED_ALL"


def test_bid_ask_filter_root_cause_classification():
    roots = roots_for([base_row(bid=0.0, ask=1.1)])
    assert roots[0]["root_cause_code"] == "BID_FILTER_ELIMINATED_ALL"
    roots = roots_for([base_row(bid=1.0, ask=0.9)])
    assert roots[0]["root_cause_code"] == "BID_ASK_FILTER_ELIMINATED_ALL"


def test_spread_filter_root_cause_classification():
    roots = roots_for([base_row(bid=1.0, ask=2.0)])
    assert roots[0]["root_cause_code"] == "SPREAD_FILTER_ELIMINATED_ALL"


def test_missing_volume_field_classification(tmp_path):
    row = base_row()
    row.pop("volume")
    roots = roots_for([row])
    assert any(root["root_cause_code"] == "FIELD_MISSING_VOLUME" for root in roots)
    summary = module.run(tmp_path / "repo", injected_rows=[row])
    assert summary["missing_volume_field_all_rows"] is True
    assert summary["zero_candidate_root_cause_primary"] == "FIELD_MISSING_VOLUME" or summary["zero_candidate_root_cause_secondary"] == "FIELD_MISSING_VOLUME"


def test_field_mapping_issue_classification_for_unmapped_bid_ask_names(tmp_path):
    row = base_row()
    row.pop("bid")
    row.pop("ask")
    row["bpx"] = 1.0
    row["apx"] = 1.1
    roots = roots_for([row])
    assert roots[0]["root_cause_code"] == "FIELD_MAPPING_ISSUE"
    summary = module.run(tmp_path / "repo", injected_rows=[row])
    assert summary["field_mapping_issue_detected"] is True
    assert summary["missing_bid_ask_field_all_rows"] is True


def test_relaxed_filter_simulation_does_not_alter_official_candidate_filter(tmp_path):
    rows = [base_row(bid=1.0, ask=2.0)]
    summary = module.run(tmp_path / "repo", injected_rows=rows, relaxed_max_spread_pct=2.0)
    sim_rows = read_rows(tmp_path / "repo" / module.OUT_REL / "live_option_relaxed_filter_simulation.csv")
    official = next(row for row in sim_rows if row["simulation_name"] == "official_filters")
    relaxed = next(row for row in sim_rows if row["simulation_name"] == "relaxed_spread_only")
    assert official["candidate_count"] == "0"
    assert int(relaxed["candidate_count"]) > 0
    assert all(row["official_candidate_filter_unchanged"] == "True" for row in sim_rows)
    assert summary["liquidity_candidate_count"] == 0


def test_broker_action_allowed_remains_false(tmp_path):
    summary = module.run(tmp_path / "repo", injected_rows=[base_row()])
    assert summary["broker_action_allowed"] is False


def test_official_adoption_allowed_remains_false(tmp_path):
    summary = module.run(tmp_path / "repo", injected_rows=[base_row()])
    assert summary["official_adoption_allowed"] is False


def test_trade_context_unlock_and_place_order_flags_remain_false(tmp_path):
    summary = module.run(tmp_path / "repo", injected_rows=[base_row()])
    assert summary["trade_context_used"] is False
    assert summary["unlock_trade_called"] is False
    assert summary["place_order_called"] is False


def test_summary_schema_stability(tmp_path):
    repo = tmp_path / "repo"
    summary = module.run(repo, injected_rows=[base_row()])
    payload = json.loads((repo / module.OUT_REL / "v22_041_r2_summary.json").read_text(encoding="utf-8"))
    for field in module.SUMMARY_FIELDS:
        assert field in summary
        assert field in payload
    for filename in REQUIRED_FILES:
        assert (repo / module.OUT_REL / filename).exists()
    expected = {
        "live_option_chain_coverage_by_underlying.csv": module.COVERAGE_FIELDS,
        "live_option_field_availability_audit.csv": module.FIELD_FIELDS,
        "live_option_filter_funnel.csv": module.FUNNEL_FIELDS,
        "live_option_zero_candidate_root_cause.csv": module.ROOT_FIELDS,
        "live_option_relaxed_filter_simulation.csv": module.RELAXED_FIELDS,
    }
    for filename, fields in expected.items():
        with (repo / module.OUT_REL / filename).open(encoding="utf-8", newline="") as handle:
            assert next(csv.reader(handle)) == fields


def test_deterministic_final_status_and_decision(tmp_path):
    first = module.run(tmp_path / "a", injected_rows=[base_row()])
    second = module.run(tmp_path / "b", injected_rows=[base_row()])
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
