from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_029_r1_current_daily_shadow_observation_rebuilder.py"

OUT_DIR = ROOT / "outputs" / "v21" / "shadow_observation"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_029_R1_CURRENT_DAILY_SHADOW_OBSERVATION_REBUILDER_REPORT.md"

LEDGER = OUT_DIR / "V21_029_R1_CURRENT_DAILY_SHADOW_OBSERVATION_LEDGER.csv"
SUMMARY = OUT_DIR / "V21_029_R1_CURRENT_DAILY_SHADOW_OBSERVATION_SUMMARY.csv"
COVERAGE = OUT_DIR / "V21_029_R1_CONTEXT_COVERAGE_AUDIT.csv"
ID_AUDIT = OUT_DIR / "V21_029_R1_OBSERVATION_ID_AUDIT.csv"
FALLBACK_AUDIT = OUT_DIR / "V21_029_R1_FALLBACK_BYPASS_AUDIT.csv"


REQUIRED_OUTPUTS = [
    LEDGER,
    SUMMARY,
    COVERAGE,
    ID_AUDIT,
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


def run_producer() -> None:
    subprocess.run(
        ["python", str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )


def test_v21_029_r1_current_daily_shadow_observation_rebuilder() -> None:
    run_producer()

    for path in REQUIRED_OUTPUTS:
        assert_non_empty(path)

    summary_rows = read_rows(SUMMARY)
    assert len(summary_rows) == 1, "summary must contain exactly one row"
    summary = summary_rows[0]

    assert summary["final_status"] == "PASS_V21_029_R1_CURRENT_DAILY_SHADOW_OBSERVATION_LEDGER_REBUILT"
    assert summary["rebuilder_decision"] == "CURRENT_DAILY_SHADOW_OBSERVATION_LEDGER_READY_FOR_MATURITY_TRACKING"
    assert summary["source_repaired_label_date"] == "2026-06-16"
    assert summary["latest_available_current_daily_candidate_date"] == "2026-06-16"
    assert int(summary["ledger_row_count"]) > 0
    assert int(summary["distinct_as_of_date_count"]) == 1
    assert int(summary["duplicate_observation_id_count"]) == 0
    assert int(summary["pending_schedule_count"]) > 0
    assert int(summary["matured_count"]) == 0
    assert int(summary["price_missing_count"]) == 0

    assert_bool(summary, "fallback_used", False)
    assert_bool(summary, "fallback_required_after_v21_032", False)
    assert_bool(summary, "current_daily_observation_allowed", True)
    assert_bool(summary, "official_use_allowed", False)
    assert_bool(summary, "official_ranking_readiness_allowed", False)
    assert_bool(summary, "official_weight_update_readiness_allowed", False)
    assert_bool(summary, "official_weight_update_blocked", True)
    assert_bool(summary, "broker_execution_supported", False)
    assert_bool(summary, "shadow_activation", False)
    assert_bool(summary, "research_only", True)
    assert summary["recommended_next_stage"] == "V21_030_R1_CURRENT_DAILY_LEDGER_MATURITY_TRACKER"
    assert summary["selected_recommended_next_stage"] == "V21_030_R1_CURRENT_DAILY_LEDGER_MATURITY_TRACKER"

    ledger_rows = read_rows(LEDGER)
    assert len(ledger_rows) == int(summary["ledger_row_count"])
    ids = [row["observation_id"] for row in ledger_rows]
    assert all(ids), "observation_id values must be non-empty"
    assert len(ids) == len(set(ids)), "observation_id values must be unique"
    assert {row["as_of_date"] for row in ledger_rows} == {"2026-06-16"}
    assert {row["source_repaired_label_date"] for row in ledger_rows} == {"2026-06-16"}
    assert {norm(row["fallback_used"]) for row in ledger_rows} == {"FALSE"}
    assert {row["snapshot_source"] for row in ledger_rows} == {"CURRENT_REPAIRED_LABEL_DAILY_PRODUCER"}
    assert {row["observation_status"] for row in ledger_rows} == {"PENDING_NOT_MATURED"}
    assert {norm(row["research_only"]) for row in ledger_rows} == {"TRUE"}

    id_audit = read_rows(ID_AUDIT)[0]
    assert int(id_audit["duplicate_observation_id_count"]) == 0
    assert id_audit["observation_id_integrity_status"] == "PASS_UNIQUE_OBSERVATION_IDS"
    assert_bool(id_audit, "research_only", True)

    fallback = read_rows(FALLBACK_AUDIT)[0]
    assert fallback["previous_fallback_as_of_date"] == "2026-06-05"
    assert fallback["current_repaired_label_date"] == "2026-06-16"
    assert_bool(fallback, "fallback_required_before_v21_032", True)
    assert_bool(fallback, "fallback_required_after_v21_032", False)
    assert_bool(fallback, "fallback_used_in_v21_029_r1", False)
    assert "FALLBACK_BYPASSED" in fallback["fallback_bypass_status"]
    assert_bool(fallback, "current_daily_observation_allowed", True)
    assert_bool(fallback, "research_only", True)

    coverage_rows = read_rows(COVERAGE)
    assert coverage_rows, "context coverage audit must contain rows"
    assert all(
        row["coverage_status"] in {"CURRENT_DAILY_CONTEXT_COVERED", "NO_CURRENT_DAILY_CONTEXT_COVERAGE"}
        for row in coverage_rows
    )

    report_text = REPORT.read_text(encoding="utf-8")
    report_lower = report_text.lower()
    assert "2026-06-16" in report_text
    assert "2026-06-05" in report_text
    assert "fallback was bypassed" in report_lower
    assert "recommended next stage" in report_lower
    assert "research-only" in report_lower
    forbidden_claims = [
        "production readiness",
        "real-book readiness",
        "official activation",
        "official ranking readiness",
        "official weight update readiness",
    ]
    for claim in forbidden_claims:
        assert f"claims {claim}" not in report_lower


if __name__ == "__main__":
    test_v21_029_r1_current_daily_shadow_observation_rebuilder()
    print("PASS test_v21_029_r1_current_daily_shadow_observation_rebuilder")
