#!/usr/bin/env python
"""Tests for V21.049-R1 repaired context maturity evaluator scaffold."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_049_r1_repaired_context_maturity_evaluator_scaffold.py"
spec = importlib.util.spec_from_file_location("v21_049_r1", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)

FIELDS = [
    "observation_id", "repaired_observation_id", "as_of_date", "ticker",
    "repaired_context_label", "lane_id", "forward_return_window",
    "scheduled_maturity_date", "maturity_status", "realized_forward_return",
    "forward_price_available", "price_missing", "research_only",
]


def fixture_row(index: int, context: str = "RSI_BULLISH", window: str = "5D") -> dict[str, str]:
    return {
        "observation_id": f"OBS_{index}",
        "repaired_observation_id": f"REPAIRED_{index}",
        "as_of_date": "2026-06-16",
        "ticker": f"T{index:03d}",
        "repaired_context_label": context,
        "lane_id": "PRIMARY",
        "forward_return_window": window,
        "scheduled_maturity_date": "2026-06-24",
        "maturity_status": "PENDING_NOT_MATURED",
        "realized_forward_return": "",
        "forward_price_available": "FALSE",
        "price_missing": "FALSE",
        "research_only": "TRUE",
    }


def write_rows(path: Path, rows: list[dict[str, str]], fields: list[str] = FIELDS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_zero_maturity_pending() -> None:
    rows = [fixture_row(index) for index in range(4)]
    summary, by_context, by_window = module.evaluate(
        rows, FIELDS, "fixture.csv", True, today=date(2026, 6, 19)
    )
    assert summary["final_status"] == module.PENDING_STATUS
    assert summary["decision"] == "WAIT_FOR_FORWARD_RETURN_MATURITY"
    assert summary["matured_row_count"] == 0
    assert summary["pending_row_count"] == 4
    assert summary["alpha_interpretation_allowed"] == "FALSE"
    assert summary["shadow_review_allowed"] == "FALSE"
    assert summary["shadow_adoption_allowed"] == "FALSE"
    assert summary["official_use_allowed"] == "FALSE"
    assert summary["broker_execution_allowed"] == "FALSE"
    assert summary["trade_action_allowed"] == "FALSE"
    assert summary["next_maturity_check_date"] == "2026-06-24"
    assert by_context == [] and by_window == []


def test_duplicate_ids_and_required_columns() -> None:
    first = fixture_row(1)
    conflict = dict(first)
    conflict["ticker"] = "DIFFERENT"
    summary, _, _ = module.evaluate(
        [first, conflict], FIELDS, "fixture.csv", True, today=date(2026, 6, 19)
    )
    assert summary["final_status"] == module.DUPLICATE_STATUS
    assert summary["duplicate_repaired_observation_id_count"] == 1

    missing_fields = [field for field in FIELDS if field != "lane_id"]
    summary, _, _ = module.evaluate(
        [fixture_row(1)], missing_fields, "fixture.csv", True, today=date(2026, 6, 19)
    )
    assert summary["final_status"] == module.COLUMNS_STATUS


def test_matured_summaries_and_thresholds() -> None:
    rows = []
    returns = [0.10, -0.05, 0.00, 0.20]
    for index, value in enumerate(returns):
        row = fixture_row(index, "RSI_BULLISH" if index < 2 else "MACD_HIST_POSITIVE", "5D" if index % 2 == 0 else "10D")
        row["maturity_status"] = "MATURED_PRICE_AVAILABLE"
        row["realized_forward_return"] = str(value)
        row["forward_price_available"] = "TRUE"
        rows.append(row)
    summary, by_context, by_window = module.evaluate(
        rows, FIELDS, "fixture.csv", True, today=date(2026, 7, 2)
    )
    assert summary["final_status"] == module.INSUFFICIENT_STATUS
    assert summary["matured_row_count"] == 4
    assert summary["alpha_interpretation_allowed"] == "FALSE"
    assert summary["shadow_review_allowed"] == "TRUE"
    rsi = next(row for row in by_context if row["repaired_context_label"] == "RSI_BULLISH")
    assert rsi["mean_realized_forward_return"] == "0.0250000000"
    assert rsi["median_realized_forward_return"] == "0.0250000000"
    assert rsi["hit_rate"] == "0.5000000000"
    assert rsi["positive_count"] == 1 and rsi["negative_count"] == 1
    five = next(row for row in by_window if row["forward_return_window"] == "5D")
    assert five["mean_realized_forward_return"] == "0.0500000000"


def test_schema_outputs_and_no_protected_mutation() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        ledger = root / "outputs/v21/context/V21_048_R1_REPAIRED_CONTEXT_OBSERVATION_LEDGER.csv"
        write_rows(ledger, [fixture_row(1)])
        write_rows(
            root / "outputs/v21/context/V21_048_R1_CONTEXT_SELECTIVITY_AUDIT_SUMMARY.csv",
            [{"context_selectivity_gate_pass": "TRUE"}],
            ["context_selectivity_gate_pass"],
        )
        protected = root / "outputs/v21/official/V21_OFFICIAL_RANKING.csv"
        protected.parent.mkdir(parents=True)
        protected.write_text("ticker,rank\nAAA,1\n", encoding="utf-8")
        before = hashlib.sha256(protected.read_bytes()).hexdigest()
        subprocess.run(
            ["python", str(SCRIPT), "--root", str(root)],
            cwd=ROOT, text=True, capture_output=True, check=True,
        )
        assert hashlib.sha256(protected.read_bytes()).hexdigest() == before
        context_path = root / "outputs/v21/context/V21_049_R1_REPAIRED_CONTEXT_MATURITY_BY_CONTEXT.csv"
        window_path = root / "outputs/v21/context/V21_049_R1_REPAIRED_CONTEXT_MATURITY_BY_WINDOW.csv"
        with context_path.open(encoding="utf-8-sig", newline="") as handle:
            assert list(csv.DictReader(handle).fieldnames or []) == module.BY_CONTEXT_FIELDS
        with window_path.open(encoding="utf-8-sig", newline="") as handle:
            assert list(csv.DictReader(handle).fieldnames or []) == module.BY_WINDOW_FIELDS
        assert context_path.read_text(encoding="utf-8").count("\n") == 1
        assert window_path.read_text(encoding="utf-8").count("\n") == 1


if __name__ == "__main__":
    test_zero_maturity_pending()
    test_duplicate_ids_and_required_columns()
    test_matured_summaries_and_thresholds()
    test_schema_outputs_and_no_protected_mutation()
    print("PASS test_v21_049_r1_repaired_context_maturity_evaluator_scaffold")
