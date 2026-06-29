from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_030_r1_current_daily_ledger_maturity_tracker.py"

OUT_DIR = ROOT / "outputs" / "v21" / "shadow_observation"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_030_R1_CURRENT_DAILY_LEDGER_MATURITY_TRACKER_REPORT.md"

DECISION = OUT_DIR / "V21_030_R1_CURRENT_DAILY_MATURITY_TRACKER_DECISION.csv"
INTEGRITY = OUT_DIR / "V21_030_R1_CURRENT_DAILY_LEDGER_INTEGRITY_AUDIT.csv"
STATUS_LEDGER = OUT_DIR / "V21_030_R1_CURRENT_DAILY_MATURITY_STATUS_LEDGER.csv"
SUMMARY_BY_CONTEXT = OUT_DIR / "V21_030_R1_CURRENT_DAILY_MATURITY_SUMMARY_BY_CONTEXT.csv"
SUMMARY_BY_WINDOW = OUT_DIR / "V21_030_R1_CURRENT_DAILY_MATURITY_SUMMARY_BY_WINDOW.csv"
SELECTIVITY = OUT_DIR / "V21_030_R1_CONTEXT_SELECTIVITY_AUDIT.csv"
FALLBACK_AUDIT = OUT_DIR / "V21_030_R1_CURRENT_DAILY_FALLBACK_AUDIT.csv"

REQUIRED_OUTPUTS = [
    DECISION,
    INTEGRITY,
    STATUS_LEDGER,
    SUMMARY_BY_CONTEXT,
    SUMMARY_BY_WINDOW,
    SELECTIVITY,
    FALLBACK_AUDIT,
    REPORT,
]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def norm(value: object) -> str:
    return str(value).strip().upper()


def assert_bool(row: dict[str, str], field: str, expected: bool) -> None:
    expected_text = "TRUE" if expected else "FALSE"
    actual = norm(row.get(field, ""))
    assert actual == expected_text, f"{field} expected {expected_text}, got {actual}"


def assert_non_empty(path: Path) -> None:
    assert path.exists(), f"missing output: {path}"
    assert path.stat().st_size > 0, f"empty output: {path}"


def run_tracker() -> None:
    subprocess.run(
        ["python", str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )


def test_v21_030_r1_current_daily_ledger_maturity_tracker() -> None:
    run_tracker()

    for path in REQUIRED_OUTPUTS:
        assert_non_empty(path)

    decision_rows = read_rows(DECISION)
    assert len(decision_rows) == 1, "decision must contain exactly one row"
    decision = decision_rows[0]
    assert decision["final_status"] == "PASS_V21_030_R1_CURRENT_DAILY_LEDGER_TRACKED_PENDING_MATURITY"
    assert decision["maturity_tracker_decision"] == "CURRENT_DAILY_LEDGER_TRACKED_PENDING_FORWARD_RETURN_MATURITY"
    assert decision["source_ledger_stage"] == "V21_029_R1_CURRENT_DAILY_SHADOW_OBSERVATION_REBUILDER"
    assert decision["source_ledger_as_of_date"] == "2026-06-16"
    assert decision["source_repaired_label_date"] == "2026-06-16"
    assert_bool(decision, "fallback_used", False)
    assert_bool(decision, "current_daily_observation_allowed", True)
    assert_bool(decision, "official_use_allowed", False)
    assert_bool(decision, "official_ranking_readiness_allowed", False)
    assert_bool(decision, "official_weight_update_readiness_allowed", False)
    assert_bool(decision, "official_weight_update_blocked", True)
    assert_bool(decision, "broker_execution_supported", False)
    assert_bool(decision, "shadow_activation", False)
    assert_bool(decision, "research_only", True)
    assert decision["recommended_next_stage"] == "V21_031_R1_CURRENT_DAILY_SHADOW_REPORT_APPEND_OR_WAIT_FOR_MATURITY"
    assert decision["selected_recommended_next_stage"] == "V21_031_R1_CURRENT_DAILY_SHADOW_REPORT_APPEND_OR_WAIT_FOR_MATURITY"

    integrity = read_rows(INTEGRITY)[0]
    assert int(integrity["row_count"]) == 4560
    assert int(integrity["unique_observation_id_count"]) == 4560
    assert int(integrity["duplicate_observation_id_count"]) == 0
    assert int(integrity["distinct_as_of_date_count"]) == 1
    assert int(integrity["distinct_ticker_count"]) == 190
    assert int(integrity["distinct_context_key_count"]) == 8
    assert int(integrity["distinct_context_label_count"]) == 8
    assert int(integrity["distinct_lane_id_count"]) == 2
    assert int(integrity["distinct_forward_return_window_count"]) == 3
    assert int(integrity["selected_observation_count"]) == 4560
    assert int(integrity["pending_schedule_count"]) == 4560
    assert_bool(integrity, "fallback_used", False)
    assert integrity["latest_as_of_date"] == "2026-06-16"
    assert integrity["source_repaired_label_date"] == "2026-06-16"
    assert integrity["snapshot_source"] == "CURRENT_REPAIRED_LABEL_DAILY_PRODUCER"
    assert_bool(integrity, "research_only_flag_consistency", True)
    assert_bool(integrity, "research_only", True)

    status_rows = read_rows(STATUS_LEDGER)
    assert len(status_rows) == 4560
    assert {row["as_of_date"] for row in status_rows} == {"2026-06-16"}
    assert {row["source_repaired_label_date"] for row in status_rows} == {"2026-06-16"}
    assert {row["maturity_status"] for row in status_rows} == {"PENDING_NOT_MATURED"}
    assert {row["realized_forward_return"] for row in status_rows} == {""}
    assert {norm(row["forward_price_available"]) for row in status_rows} == {"FALSE"}
    assert {norm(row["price_missing"]) for row in status_rows} == {"FALSE"}
    assert {norm(row["fallback_used"]) for row in status_rows} == {"FALSE"}
    assert {norm(row["research_only"]) for row in status_rows} == {"TRUE"}

    context_rows = read_rows(SUMMARY_BY_CONTEXT)
    assert len(context_rows) == 8
    assert all(int(row["scheduled_count"]) == 570 for row in context_rows)
    assert all(int(row["matured_count"]) == 0 for row in context_rows)
    assert all(int(row["pending_count"]) == 570 for row in context_rows)
    assert all(int(row["price_missing_count"]) == 0 for row in context_rows)
    assert all(row["mean_realized_forward_return"] == "" for row in context_rows)
    assert all(row["maturity_summary_status"] == "PENDING_OBSERVATION_MATURITY" for row in context_rows)

    window_rows = read_rows(SUMMARY_BY_WINDOW)
    assert {row["forward_return_window"] for row in window_rows} == {"5D", "10D", "20D"}
    assert all(int(row["scheduled_count"]) == 1520 for row in window_rows)
    assert all(int(row["matured_count"]) == 0 for row in window_rows)
    assert all(int(row["pending_count"]) == 1520 for row in window_rows)
    assert all(int(row["price_missing_count"]) == 0 for row in window_rows)
    assert all(row["maturity_summary_status"] == "PENDING_OBSERVATION_MATURITY" for row in window_rows)

    selectivity_rows = read_rows(SELECTIVITY)
    assert len(selectivity_rows) == 8
    assert all(row["context_selectivity_status"] == "CONTEXT_OVER_BROADCAST_ALL_TICKERS" for row in selectivity_rows)
    assert all(norm(row["alpha_interpretation_allowed"]) == "FALSE" for row in selectivity_rows)
    assert all(int(row["distinct_ticker_count"]) == 190 for row in selectivity_rows)
    assert all(row["ticker_coverage_ratio"] == "1.0000000000" for row in selectivity_rows)

    fallback = read_rows(FALLBACK_AUDIT)[0]
    assert fallback["previous_fallback_as_of_date"] == "2026-06-05"
    assert fallback["current_ledger_as_of_date"] == "2026-06-16"
    assert fallback["source_repaired_label_date"] == "2026-06-16"
    assert_bool(fallback, "fallback_used_in_v21_029_r1", False)
    assert_bool(fallback, "fallback_used_in_v21_030_r1", False)
    assert "FALLBACK_BYPASSED" in fallback["fallback_bypass_status"]
    assert_bool(fallback, "current_daily_observation_allowed", True)
    assert_bool(fallback, "research_only", True)

    report_text = REPORT.read_text(encoding="utf-8")
    report_lower = report_text.lower()
    assert "2026-06-16 current daily ledger" in report_lower
    assert "2026-06-05 fallback bypass" in report_lower
    assert "pending maturity" in report_lower
    assert "context over-broadcast warning" in report_lower
    assert "alpha interpretation is not allowed" in report_lower
    assert "research-only" in report_lower


if __name__ == "__main__":
    test_v21_030_r1_current_daily_ledger_maturity_tracker()
    print("PASS test_v21_030_r1_current_daily_ledger_maturity_tracker")
