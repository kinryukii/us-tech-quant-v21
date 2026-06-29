#!/usr/bin/env python
"""Validate V21.132 data-quality waiver record and maturity-first transition."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.132_D_DATA_QUALITY_WAIVER_RECORD_AND_MATURITY_FIRST_TRANSITION"
OUT = ROOT / "outputs/v21/V21.132_D_DATA_QUALITY_WAIVER_RECORD_AND_MATURITY_FIRST_TRANSITION"
MAIN_SCRIPT = ROOT / "scripts/v21/v21_132_d_data_quality_waiver_record_and_maturity_first_transition.py"

SUMMARY = OUT / "V21.132_summary.json"
READABLE = OUT / "V21.132_readable_report.txt"
COMPACT = OUT / "V21.132_compact_report.txt"
WAIVER_RECORD = OUT / "V21.132_data_quality_waiver_record.csv"
TRANSITION = OUT / "V21.132_primary_blocker_transition.csv"
MATURITY_PLAN = OUT / "V21.132_d_maturity_first_monitoring_plan.csv"
REMAINING = OUT / "V21.132_remaining_blockers_after_data_quality_waiver.csv"

EXPECTED_REMAINING = {
    "MATURITY",
    "VS_A1_PERFORMANCE",
    "VS_QQQ_PERFORMANCE",
    "CONCENTRATION_RISK",
    "LEFT_TAIL_DRAWDOWN_RISK",
    "REPEATED_LOSER_RISK",
    "REGIME_COMPATIBILITY",
}

EXPECTED_PROTECTED_SHA256 = {
    "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/V21.128_summary.json": "9769d42521e1aace56930c2e4d553de4472c77d176d64143cf1751211233a71c",
    "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/V21.128_readable_report.txt": "bd6e99582cf23f201aaf9d4b340a2cb7139c9d8bd6dd2d6dbac0cc929dba2af3",
    "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/V21.128_compact_report.txt": "8763446cf2d70e3712ec6a247819e334db0a9b63740151b40b91169be841835a",
    "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv": "014bc942860b969185090998730178177a740b52b1985d8c2134e8299b3c3f01",
    "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/A1_BASELINE_CONTROL_latest_ranking.csv": "60197c9c964b2666258a2d5154ff2b97d9ca667aed964a1585653afe570d59a9",
    "outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE/V21.129_summary.json": "ebe5b19cdd98e6865e5d501f9307119628fb81ce28c0cfcc831849dea7fd74ff",
    "outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE/V21.129_d_strict_gate_results.csv": "14c96de363f7c9999a228e7b612724490461822ea4ce255bda03037e53eb74c1",
    "outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE/V21.129_d_tracking_top20.csv": "b0c4e1b1b3176927d696f599fcf9f24581682836919b3b4844579c40be585c44",
    "outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE/V21.129_d_tracking_top50.csv": "6e4d692fdd50db3722282258c4405378aad21ac7656a104793a41f05bdc8ad1a",
    "outputs/v21/V21.130_D_STRICT_GATE_EVIDENCE_LEDGER_AND_BLOCK_REASON_DECOMPOSITION/V21.130_summary.json": "7b540024f2ea643f41bdf41ef64d7017955e7e1272b7fab080af78118bb08c72",
    "outputs/v21/V21.130_D_STRICT_GATE_EVIDENCE_LEDGER_AND_BLOCK_REASON_DECOMPOSITION/V21.130_d_gate_evidence_ledger.csv": "cf3045490bdbdf154beed832f21b20243986a9c690f2564a9dafecd661935225",
    "outputs/v21/V21.131_D_DATA_QUALITY_BLOCKER_ROOT_CAUSE_AND_WAIVER_PROTOCOL/V21.131_summary.json": "94e574b26223789c783d94b0c225fbf2cd0888abc5052b607cc8ea836c36114f",
    "outputs/v21/V21.131_D_DATA_QUALITY_BLOCKER_ROOT_CAUSE_AND_WAIVER_PROTOCOL/V21.131_affected_ticker_impact_analysis.csv": "ff560a491baf1244801f2b7eac31a8ee9d8bd396cc0cbdde80bcdffcc0e44bfa",
    "outputs/v21/V21.131_D_DATA_QUALITY_BLOCKER_ROOT_CAUSE_AND_WAIVER_PROTOCOL/V21.131_waiver_eligibility_assessment.csv": "ddb5b11a478d91ecdc594534ad97d2e589dcc738c5f650d682ddb1959c102b40",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def validate_files() -> None:
    for path in [MAIN_SCRIPT, OUT, SUMMARY, READABLE, COMPACT, WAIVER_RECORD, TRANSITION, MATURITY_PLAN, REMAINING]:
        require(path.exists(), f"missing required path: {path}")


def validate_summary(summary: dict[str, Any]) -> None:
    require(summary.get("stage") == STAGE, "summary stage mismatch")
    require(summary.get("FINAL_STATUS") == "PASS_V21_132_D_WAIVER_RECORD_READY_MATURITY_FIRST", "unexpected final status")
    require(summary.get("DECISION") == "D_DATA_WARNING_WAIVER_REVIEW_READY_ADOPTION_STILL_BLOCKED", "unexpected decision")
    require(summary.get("warning_ticker") == "PSTG", "warning_ticker must be PSTG")
    require(summary.get("data_quality_impact_classification") == "NON_D_WARNING_LOW_IMPACT", "unexpected impact classification")
    require(as_bool(summary.get("DATA_QUALITY_WAIVER_ELIGIBLE")) is True, "waiver_eligible must be true")
    require(as_bool(summary.get("DATA_QUALITY_WAIVER_REVIEW_REQUIRED")) is True, "waiver_review_required must be true")
    require(as_bool(summary.get("DATA_QUALITY_WAIVER_APPLIED")) is False, "waiver_applied must be false")
    require(summary.get("projected_primary_D_blocker_if_waived") == "INSUFFICIENT_MATURITY", "projected primary blocker must be maturity")
    require(as_bool(summary.get("D_adoption_allowed")) is False, "D_adoption_allowed must be false")
    require(as_bool(summary.get("role_review_required")) is False, "role_review_required must be false")
    require(as_bool(summary.get("official_adoption_allowed")) is False, "official_adoption_allowed must be false")
    require(as_bool(summary.get("broker_action_allowed")) is False, "broker_action_allowed must be false")
    require(as_bool(summary.get("protected_outputs_modified")) is False, "protected_outputs_modified must be false")
    require(as_bool(summary.get("research_only")) is True, "research_only must be true")
    require(as_bool(summary.get("v21_128_v21_129_v21_130_v21_131_baseline_preserved")) is True, "baseline preservation flag must be true")


def validate_csv_outputs() -> None:
    waiver = read_csv(WAIVER_RECORD)
    require(len(waiver) == 1, "waiver record must have one row")
    row = waiver[0]
    require(row["warning_ticker"] == "PSTG", "waiver record warning ticker mismatch")
    require(as_bool(row["waiver_eligible"]) is True, "waiver record eligibility must be true")
    require(as_bool(row["waiver_review_required"]) is True, "waiver review required must be true")
    require(as_bool(row["waiver_applied"]) is False, "waiver must not be applied")

    transition = read_csv(TRANSITION)
    require(transition and transition[0]["current_primary_D_blocker"] == "DATA_QUALITY_WARNING", "current primary blocker mismatch")
    require(transition[0]["projected_primary_D_blocker_if_waived"] == "INSUFFICIENT_MATURITY", "transition projected blocker mismatch")
    require(transition[0]["transition_status"] == "READY_FOR_MATURITY_FIRST_MONITORING", "transition status mismatch")

    maturity = read_csv(MATURITY_PLAN)
    require({row["maturity_metric"] for row in maturity} == {"D_matured_top20_observations", "D_matured_top50_observations", "distinct_forward_ranking_dates"}, "maturity metrics incomplete")
    require(all(row["next_action_gate"] == "WAIT_MORE_D_MATURITY" for row in maturity), "maturity next action mismatch")

    remaining = read_csv(REMAINING)
    blockers = {row["remaining_blocker"] for row in remaining}
    require(blockers == EXPECTED_REMAINING, "remaining blockers were not preserved")
    require(all(as_bool(row["data_quality_waiver_changes_adoption_status"]) is False for row in remaining), "data-quality waiver must not change adoption status")


def validate_protected_hashes() -> None:
    for rel_path, expected in EXPECTED_PROTECTED_SHA256.items():
        path = ROOT / rel_path
        require(path.is_file(), f"missing protected file: {rel_path}")
        require(sha256(path) == expected, f"protected baseline changed: {rel_path}")


def main() -> None:
    validate_files()
    summary = load_json(SUMMARY)
    validate_summary(summary)
    validate_csv_outputs()
    validate_protected_hashes()
    print("V21.132 validation PASS")
    print(f"summary_path={SUMMARY.relative_to(ROOT).as_posix()}")
    print(f"warning_ticker={summary.get('warning_ticker')}")
    print(f"projected_primary_D_blocker_if_waived={summary.get('projected_primary_D_blocker_if_waived')}")


if __name__ == "__main__":
    main()
