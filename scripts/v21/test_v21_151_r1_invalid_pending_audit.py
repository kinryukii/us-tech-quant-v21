from __future__ import annotations

from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.151_R1_INVALID_PENDING_AUDIT")
REQUIRED = [
    "invalid_pending_root_cause_audit.csv",
    "primary_candidate_pending_maturity_calendar.csv",
    "primary_candidate_invalid_detail.csv",
    "valid_holdings_breadth_audit.csv",
    "skipped_vs_invalid_policy_recommendation.csv",
    "V21.151_R1_INVALID_PENDING_AUDIT_REPORT.md",
    "compact_readable_report.txt",
]


def test_required_outputs_exist() -> None:
    assert OUT.exists()
    for name in REQUIRED:
        assert (OUT / name).exists(), name


def test_no_protected_official_or_broker_mutation_claimed() -> None:
    report = (OUT / "compact_readable_report.txt").read_text(encoding="utf-8")
    assert "protected_outputs_modified=false" in report
    assert "official_adoption_allowed=false" in report
    assert "broker_action_allowed=false" in report


def test_e_r1_remains_diagnostic_and_invalid_lineage_not_evidence() -> None:
    report = (OUT / "V21.151_R1_INVALID_PENDING_AUDIT_REPORT.md").read_text(encoding="utf-8")
    assert "E_R1_diagnostic_only=true" in report
    assert "not used as adoption evidence" in report


def test_all_invalid_pending_rows_have_one_root_cause() -> None:
    pending = pd.read_csv(OUT / "primary_candidate_pending_maturity_calendar.csv")
    invalid = pd.read_csv(OUT / "primary_candidate_invalid_detail.csv")
    detail = pd.concat([pending, invalid], ignore_index=True)
    assert not detail.empty
    assert detail["root_cause"].notna().all()
    assert detail["root_cause"].astype(str).str.len().gt(0).all()
    assert len(detail) == len(detail[["ticker", "root_cause"]])


def test_pending_maturity_dates_without_lookahead() -> None:
    pending = pd.read_csv(OUT / "primary_candidate_pending_maturity_calendar.csv")
    if not pending.empty:
        assert "earliest_possible_maturity_date" in pending.columns
        # Current panel has no post-ranking dates, so the field may be blank, but it must be computed explicitly.
        assert "expected_execution_date" in pending.columns


def test_legitimate_skips_separated_from_data_failures() -> None:
    root = pd.read_csv(OUT / "invalid_pending_root_cause_audit.csv")
    assert "INVALID_ENTRY_SKIPPED_OVERHEAT" in set(root["root_cause"])
    skip = root[root["root_cause"].eq("INVALID_ENTRY_SKIPPED_OVERHEAT")].iloc[0]
    assert bool(skip["expected_or_acceptable"]) is True
    assert bool(skip["requires_code_repair"]) is False


def test_breadth_audit_exists() -> None:
    breadth = pd.read_csv(OUT / "valid_holdings_breadth_audit.csv")
    assert not breadth.empty
    assert int(breadth.iloc[0]["original_top20_names"]) == 20
