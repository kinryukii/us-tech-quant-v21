#!/usr/bin/env python
"""Tests for V21.032 current repaired label daily producer."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_032_current_repaired_label_daily_producer.py"
OUT_DIR = ROOT / "outputs" / "v21" / "shadow_observation"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_032_CURRENT_REPAIRED_LABEL_DAILY_PRODUCER_REPORT.md"

REQUIRED = [
    OUT_DIR / "V21_032_CURRENT_REPAIRED_LABEL_DAILY_PRODUCER_SUMMARY.csv",
    OUT_DIR / "V21_032_CURRENT_REPAIRED_LABELS.csv",
    OUT_DIR / "V21_032_LABEL_SOURCE_FIELD_AUDIT.csv",
    OUT_DIR / "V21_032_FALLBACK_REPAIR_AUDIT.csv",
    REPORT,
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_v21_032_contract() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "STAGE_NAME=V21_032_CURRENT_REPAIRED_LABEL_DAILY_PRODUCER" in result.stdout
    for path in REQUIRED:
        assert path.exists(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"

    summary = read_csv(OUT_DIR / "V21_032_CURRENT_REPAIRED_LABEL_DAILY_PRODUCER_SUMMARY.csv")[0]
    assert summary["latest_available_current_daily_candidate_date"] == "2026-06-16"
    assert summary["previous_repaired_label_latest_date"] == "2026-06-05"
    assert summary["date_gap_days_before"] == "11"
    assert summary["official_use_allowed"] == "FALSE"
    assert summary["official_ranking_readiness_allowed"] == "FALSE"
    assert summary["official_weight_update_readiness_allowed"] == "FALSE"
    assert summary["official_weight_update_blocked"] == "TRUE"
    assert summary["broker_execution_supported"] == "FALSE"
    assert summary["shadow_activation"] == "FALSE"
    assert summary["research_only"] == "TRUE"
    assert summary["selected_recommended_next_stage"] == "TRUE"

    field_audit = read_csv(OUT_DIR / "V21_032_LABEL_SOURCE_FIELD_AUDIT.csv")
    fallback = read_csv(OUT_DIR / "V21_032_FALLBACK_REPAIR_AUDIT.csv")
    assert field_audit
    assert fallback

    labels = read_csv(OUT_DIR / "V21_032_CURRENT_REPAIRED_LABELS.csv")
    produced = summary["produced_label_rows"] != "0"
    if produced:
        assert summary["produced_repaired_label_date"] == "2026-06-16"
        assert all(row["as_of_date"] == "2026-06-16" for row in labels)
        assert all(row["research_only"] == "TRUE" for row in labels)
        assert all(row["repaired_label_status"] == "DERIVED_RESEARCH_ONLY_CURRENT_DAILY" for row in labels)
    if summary["fallback_required_after"] == "FALSE":
        assert summary["current_daily_observation_allowed_after"] == "TRUE"
    if summary["producer_decision"] == "CURRENT_REPAIRED_LABEL_DAILY_PRODUCTION_BLOCKED_NO_USABLE_FIELDS":
        assert summary["fallback_required_after"] == "TRUE"

    report = REPORT.read_text(encoding="utf-8")
    assert "2026-06-05" in report
    assert "2026-06-16" in report
    assert "Gap before: 11 days" in report


if __name__ == "__main__":
    test_v21_032_contract()
    print("V21.032 current repaired label daily producer tests passed")
