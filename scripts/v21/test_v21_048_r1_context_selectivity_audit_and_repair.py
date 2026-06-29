#!/usr/bin/env python
"""Tests for V21.048-R1 context selectivity audit and repair."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_048_r1_context_selectivity_audit_and_repair.py"
spec = importlib.util.spec_from_file_location("v21_048_r1", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


FIELDS = [
    "observation_id", "as_of_date", "ticker", "context_key", "context_label",
    "lane_id", "forward_return_window", "observation_status", "maturity_status",
    "realized_forward_return", "forward_price_available", "price_missing",
    "source_repaired_label_date", "snapshot_source", "fallback_used",
    "selected_observation", "pending_schedule", "research_only",
]


def broadcast_fixture() -> list[dict[str, str]]:
    rows = []
    for ticker in ("AAA", "BBB", "CCC", "DDD"):
        for context in ("risk_on", "QQQ_uptrend", "BASELINE"):
            rows.append({
                "observation_id": f"{ticker}-{context}",
                "as_of_date": "2026-06-16",
                "ticker": ticker,
                "context_key": context,
                "context_label": context,
                "lane_id": "PRIMARY",
                "forward_return_window": "5D",
                "observation_status": "PENDING_NOT_MATURED",
                "maturity_status": "PENDING_NOT_MATURED",
                "realized_forward_return": "",
                "research_only": "TRUE",
            })
    return rows


def predicate_fixture() -> list[dict[str, str]]:
    return [
        {"as_of_date": "2026-06-16", "ticker": "AAA", "rsi_14": "75", "macd_hist": "1", "kdj_cross_state": "GOLDEN_CROSS"},
        {"as_of_date": "2026-06-16", "ticker": "BBB", "rsi_14": "25", "macd_hist": "-1", "kdj_cross_state": "DEATH_CROSS"},
        {"as_of_date": "2026-06-16", "ticker": "CCC", "rsi_14": "60", "macd_hist": "1", "bb_position": "0.9"},
        {"as_of_date": "2026-06-16", "ticker": "DDD", "rsi_14": "50", "macd_hist": "-1", "ma50_distance": "-0.1"},
    ]


def test_broadcast_and_global_detection() -> None:
    audit = module.coverage(broadcast_fixture(), "context_label", "ORIGINAL")
    by_label = {row["context_label"]: row for row in audit}
    assert by_label["risk_on"]["broadcast_context"] == "TRUE"
    assert by_label["QQQ_uptrend"]["broadcast_context"] == "TRUE"
    assert by_label["BASELINE"]["global_fallback_context"] == "TRUE"
    assert by_label["BASELINE"]["broadcast_context"] == "FALSE"


def test_repair_selectivity_uniqueness_and_columns() -> None:
    summary, coverage, repaired, repaired_fields = module.evaluate(
        broadcast_fixture(), FIELDS, predicate_fixture(), "fixture.csv"
    )
    assert summary["final_status"] == module.PASS_STATUS
    assert summary["context_selectivity_gate_pass"] == "TRUE"
    assert summary["broadcast_context_count_after"] < summary["broadcast_context_count_before"]
    assert summary["alpha_interpretation_allowed"] == "FALSE"
    assert len({row["observation_id"] for row in repaired}) == len(repaired)
    assert module.REQUIRED_COLUMNS.issubset(repaired_fields)
    repaired_audit = [row for row in coverage if row["audit_phase"] == "REPAIRED"]
    assert any(
        row["global_fallback_context"] == "FALSE" and float(row["ticker_coverage_ratio"]) < 0.95
        for row in repaired_audit
    )
    assert not all(
        {row["ticker"] for row in repaired if row["repaired_context_label"] == label}
        == {"AAA", "BBB", "CCC", "DDD"}
        for label in {row["repaired_context_label"] for row in repaired}
        if not module.is_global_context(label)
    )


def test_no_predicates_blocks_without_fabrication() -> None:
    summary, coverage, repaired, _ = module.evaluate(
        broadcast_fixture(), FIELDS, [], "fixture.csv"
    )
    assert summary["final_status"] == module.NO_PREDICATES_STATUS
    assert summary["context_selectivity_gate_pass"] == "FALSE"
    assert summary["alpha_interpretation_allowed"] == "FALSE"
    assert repaired == []
    assert all(summary[field] == "FALSE" for field in (
        "official_use_allowed", "shadow_adoption_allowed", "trade_action_allowed"
    ))
    assert summary["research_only"] == "TRUE"


def test_matured_evidence_required_for_alpha() -> None:
    assert not module.is_matured_status("PENDING_NOT_MATURED")
    rows = broadcast_fixture()
    for row in rows:
        row["maturity_status"] = "MATURED_PRICE_AVAILABLE"
        row["realized_forward_return"] = ""
    summary, _, _, _ = module.evaluate(rows, FIELDS, predicate_fixture(), "fixture.csv")
    assert summary["context_selectivity_gate_pass"] == "TRUE"
    assert summary["alpha_interpretation_allowed"] == "FALSE"


if __name__ == "__main__":
    test_broadcast_and_global_detection()
    test_repair_selectivity_uniqueness_and_columns()
    test_no_predicates_blocks_without_fabrication()
    test_matured_evidence_required_for_alpha()
    print("PASS test_v21_048_r1_context_selectivity_audit_and_repair")
