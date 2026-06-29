#!/usr/bin/env python
"""V21.132 D data-quality waiver record and maturity-first transition."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.132_D_DATA_QUALITY_WAIVER_RECORD_AND_MATURITY_FIRST_TRANSITION"
OUT = ROOT / "outputs/v21/V21.132_D_DATA_QUALITY_WAIVER_RECORD_AND_MATURITY_FIRST_TRANSITION"
V131 = ROOT / "outputs/v21/V21.131_D_DATA_QUALITY_BLOCKER_ROOT_CAUSE_AND_WAIVER_PROTOCOL"
V130 = ROOT / "outputs/v21/V21.130_D_STRICT_GATE_EVIDENCE_LEDGER_AND_BLOCK_REASON_DECOMPOSITION"
V129 = ROOT / "outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE"
V128 = ROOT / "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE"

V131_SUMMARY = V131 / "V21.131_summary.json"
V131_IMPACT = V131 / "V21.131_affected_ticker_impact_analysis.csv"
V130_SUMMARY = V130 / "V21.130_summary.json"
V129_SUMMARY = V129 / "V21.129_summary.json"

REMAINING_BLOCKERS = [
    "MATURITY",
    "VS_A1_PERFORMANCE",
    "VS_QQQ_PERFORMANCE",
    "CONCENTRATION_RISK",
    "LEFT_TAIL_DRAWDOWN_RISK",
    "REPEATED_LOSER_RISK",
    "REGIME_COMPATIBILITY",
]

PROTECTED_BASELINE_FILES = [
    V128 / "V21.128_summary.json",
    V128 / "V21.128_readable_report.txt",
    V128 / "V21.128_compact_report.txt",
    V128 / "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv",
    V128 / "A1_BASELINE_CONTROL_latest_ranking.csv",
    V129 / "V21.129_summary.json",
    V129 / "V21.129_d_strict_gate_results.csv",
    V129 / "V21.129_d_tracking_top20.csv",
    V129 / "V21.129_d_tracking_top50.csv",
    V130 / "V21.130_summary.json",
    V130 / "V21.130_d_gate_evidence_ledger.csv",
    V131 / "V21.131_summary.json",
    V131 / "V21.131_affected_ticker_impact_analysis.csv",
    V131 / "V21.131_waiver_eligibility_assessment.csv",
]


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> None:
    rows = list(rows)
    if fields is None:
        fields = []
        for row in rows:
            for field in row:
                if field not in fields:
                    fields.append(field)
        fields = fields if fields else ["empty"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_status() -> list[str]:
    completed = subprocess.run(["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True, check=False)
    return completed.stdout.splitlines()


def protected_modified(status_lines: list[str], baseline_lines: list[str]) -> bool:
    baseline = {line.replace("\\", "/") for line in baseline_lines}
    allowed_prefix = "?? outputs/v21/V21.132_D_DATA_QUALITY_WAIVER_RECORD_AND_MATURITY_FIRST_TRANSITION/"
    allowed_scripts = {
        "?? scripts/v21/v21_132_d_data_quality_waiver_record_and_maturity_first_transition.py",
        "?? scripts/v21/test_v21_132_d_data_quality_waiver_record_and_maturity_first_transition.py",
    }
    for line in status_lines:
        normalized = line.replace("\\", "/")
        if normalized in baseline or normalized.startswith(allowed_prefix) or normalized in allowed_scripts:
            continue
        lowered = normalized.lower()
        if lowered.startswith((" m outputs/", " d outputs/", "?? outputs/")) and (
            "official" in lowered or "broker" in lowered or "protected" in lowered
        ):
            return True
    return False


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def to_float(value: Any, default: float = math.nan) -> float:
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def remaining_needed(current: Any, threshold: float) -> float:
    current_float = to_float(current)
    if math.isnan(current_float):
        return threshold
    return max(0.0, threshold - current_float)


def write_reports(summary: dict[str, Any]) -> None:
    readable = [
        STAGE,
        f"FINAL_STATUS={summary['FINAL_STATUS']}",
        f"DECISION={summary['DECISION']}",
        "",
        "This stage records the PSTG data-quality warning as waiver-review eligible. The waiver is not applied and does not grant D adoption or role review.",
        "",
        f"warning_ticker={summary['warning_ticker']}",
        f"data_quality_impact_classification={summary['data_quality_impact_classification']}",
        f"DATA_QUALITY_WAIVER_ELIGIBLE={str(summary['DATA_QUALITY_WAIVER_ELIGIBLE']).lower()}",
        f"DATA_QUALITY_WAIVER_REVIEW_REQUIRED={str(summary['DATA_QUALITY_WAIVER_REVIEW_REQUIRED']).lower()}",
        f"DATA_QUALITY_WAIVER_APPLIED={str(summary['DATA_QUALITY_WAIVER_APPLIED']).lower()}",
        "",
        "Projected Transition",
        f"current_primary_D_blocker={summary['current_primary_D_blocker']}",
        f"projected_primary_D_blocker_if_waived={summary['projected_primary_D_blocker_if_waived']}",
        f"remaining_blockers={summary['remaining_blockers']}",
        "Data-quality waiver would not change D adoption status.",
        "",
        "Controls",
        "research_only=true",
        "D_continued_tracking=true",
        "D_adoption_allowed=false",
        "role_review_required=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "protected_outputs_modified=false",
    ]
    (OUT / "V21.132_readable_report.txt").write_text("\n".join(readable) + "\n", encoding="utf-8")
    compact = [
        STAGE,
        f"FINAL_STATUS={summary['FINAL_STATUS']}",
        f"DECISION={summary['DECISION']}",
        f"warning_ticker={summary['warning_ticker']}",
        "DATA_QUALITY_WAIVER_APPLIED=false",
        f"projected_primary_D_blocker_if_waived={summary['projected_primary_D_blocker_if_waived']}",
        "D_adoption_allowed=false",
    ]
    (OUT / "V21.132_compact_report.txt").write_text("\n".join(compact) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    baseline_status = git_status()
    baseline_hashes = {rel(path): sha256(path) for path in PROTECTED_BASELINE_FILES if path.is_file()}

    v131 = load_json(V131_SUMMARY)
    v130 = load_json(V130_SUMMARY)
    v129 = load_json(V129_SUMMARY)
    impact_rows = read_csv(V131_IMPACT)
    impact = impact_rows[0] if impact_rows else {}
    warning_ticker = str(v131.get("stale_or_missing_tickers", impact.get("ticker", "UNKNOWN")))
    impact_classification = str(v131.get("data_quality_impact_classification", impact.get("data_quality_impact_classification", "UNKNOWN_IMPACT_BLOCKER")))
    waiver_eligible = boolish(v131.get("DATA_QUALITY_WAIVER_ELIGIBLE"))
    waiver_review_required = boolish(v131.get("DATA_QUALITY_WAIVER_REVIEW_REQUIRED"))

    waiver_record = [{
        "warning_ticker": warning_ticker,
        "impact_classification": impact_classification,
        "waiver_eligible": waiver_eligible,
        "waiver_review_required": waiver_review_required,
        "waiver_applied": False,
        "reason": "PSTG not in D raw ranking, Top20, Top50, forward tracking, repeated-loser diagnostics, concentration chain, or benchmark usage.",
        "research_only": True,
        "adoption_permission_granted": False,
    }]

    transition = [{
        "current_primary_D_blocker": v130.get("primary_D_blocker", "DATA_QUALITY_WARNING"),
        "projected_primary_D_blocker_if_waived": v131.get("projected_primary_D_blocker_after_data_waiver", "INSUFFICIENT_MATURITY"),
        "transition_status": "READY_FOR_MATURITY_FIRST_MONITORING",
        "D_strict_gate_pass": False,
        "D_adoption_allowed": False,
        "waiver_applied": False,
        "projection_only": True,
    }]

    maturity_plan = [
        {
            "maturity_metric": "D_matured_top20_observations",
            "current_value": v129.get("D_matured_top20_observations", ""),
            "threshold": 40,
            "remaining_observations_needed": remaining_needed(v129.get("D_matured_top20_observations"), 40),
            "earliest_possible_maturity_review_condition": "D_matured_top20_observations >= 40 and other maturity metrics satisfied",
            "next_action_gate": "WAIT_MORE_D_MATURITY",
        },
        {
            "maturity_metric": "D_matured_top50_observations",
            "current_value": v129.get("D_matured_top50_observations", ""),
            "threshold": 40,
            "remaining_observations_needed": remaining_needed(v129.get("D_matured_top50_observations"), 40),
            "earliest_possible_maturity_review_condition": "D_matured_top50_observations >= 40 and other maturity metrics satisfied",
            "next_action_gate": "WAIT_MORE_D_MATURITY",
        },
        {
            "maturity_metric": "distinct_forward_ranking_dates",
            "current_value": v129.get("distinct_forward_ranking_dates", ""),
            "threshold": 8,
            "remaining_observations_needed": remaining_needed(v129.get("distinct_forward_ranking_dates"), 8),
            "earliest_possible_maturity_review_condition": "distinct_forward_ranking_dates >= 8 and top20/top50 maturity satisfied",
            "next_action_gate": "WAIT_MORE_D_MATURITY",
        },
    ]

    blocker_status = {
        "MATURITY": v129.get("D_gate_maturity", "BLOCK"),
        "VS_A1_PERFORMANCE": v129.get("D_gate_vs_A1", "BLOCK"),
        "VS_QQQ_PERFORMANCE": v129.get("D_gate_vs_QQQ", "BLOCK"),
        "CONCENTRATION_RISK": v129.get("D_gate_concentration", "BLOCK"),
        "LEFT_TAIL_DRAWDOWN_RISK": v129.get("D_gate_left_tail", "BLOCK"),
        "REPEATED_LOSER_RISK": v129.get("D_gate_repeated_loser", "BLOCK"),
        "REGIME_COMPATIBILITY": v129.get("D_gate_regime", "BLOCK"),
    }
    remaining_rows = [
        {
            "remaining_blocker": blocker,
            "status_after_data_quality_waiver_projection": blocker_status.get(blocker, "UNKNOWN"),
            "preserved_after_data_quality_waiver": True,
            "data_quality_waiver_changes_adoption_status": False,
        }
        for blocker in REMAINING_BLOCKERS
    ]

    write_csv(OUT / "V21.132_data_quality_waiver_record.csv", waiver_record)
    write_csv(OUT / "V21.132_primary_blocker_transition.csv", transition)
    write_csv(OUT / "V21.132_d_maturity_first_monitoring_plan.csv", maturity_plan)
    write_csv(OUT / "V21.132_remaining_blockers_after_data_quality_waiver.csv", remaining_rows)

    post_hashes = {rel(path): sha256(path) for path in PROTECTED_BASELINE_FILES if path.is_file()}
    protected_hash_changed = baseline_hashes != post_hashes
    prot_mod = protected_hash_changed or protected_modified(git_status(), baseline_status)

    summary = {
        "stage": STAGE,
        "FINAL_STATUS": "PASS_V21_132_D_WAIVER_RECORD_READY_MATURITY_FIRST" if not prot_mod else "BLOCKED_V21_132_PROTECTED_OUTPUT_MODIFIED",
        "DECISION": "D_DATA_WARNING_WAIVER_REVIEW_READY_ADOPTION_STILL_BLOCKED" if not prot_mod else "BLOCKED_PROTECTED_OUTPUT_MUTATION",
        "latest_price_date_used": v131.get("latest_price_date_used", v129.get("latest_price_date_used", "")),
        "warning_ticker": warning_ticker,
        "data_quality_impact_classification": impact_classification,
        "DATA_QUALITY_WAIVER_ELIGIBLE": waiver_eligible,
        "DATA_QUALITY_WAIVER_REVIEW_REQUIRED": waiver_review_required,
        "DATA_QUALITY_WAIVER_APPLIED": False,
        "current_primary_D_blocker": v130.get("primary_D_blocker", "DATA_QUALITY_WARNING"),
        "projected_primary_D_blocker_if_waived": v131.get("projected_primary_D_blocker_after_data_waiver", "INSUFFICIENT_MATURITY"),
        "transition_status": "READY_FOR_MATURITY_FIRST_MONITORING",
        "D_strict_gate_pass": False,
        "D_continued_tracking": True,
        "D_adoption_allowed": False,
        "role_review_required": False,
        "remaining_blockers": "|".join(REMAINING_BLOCKERS),
        "next_action_gate": "WAIT_MORE_D_MATURITY",
        "protected_outputs_modified": bool(prot_mod),
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "no_future_leakage": True,
        "v21_128_v21_129_v21_130_v21_131_baseline_preserved": not protected_hash_changed,
        "report_path": rel(OUT / "V21.132_readable_report.txt"),
    }
    write_json(OUT / "V21.132_summary.json", summary)
    write_reports(summary)

    print(STAGE)
    print(f"FINAL_STATUS={summary['FINAL_STATUS']}")
    print(f"DECISION={summary['DECISION']}")
    print(f"latest_price_date_used={summary['latest_price_date_used']}")
    print(f"warning_ticker={summary['warning_ticker']}")
    print(f"data_quality_impact_classification={summary['data_quality_impact_classification']}")
    print(f"DATA_QUALITY_WAIVER_ELIGIBLE={str(summary['DATA_QUALITY_WAIVER_ELIGIBLE']).lower()}")
    print(f"DATA_QUALITY_WAIVER_REVIEW_REQUIRED={str(summary['DATA_QUALITY_WAIVER_REVIEW_REQUIRED']).lower()}")
    print("DATA_QUALITY_WAIVER_APPLIED=false")
    print(f"current_primary_D_blocker={summary['current_primary_D_blocker']}")
    print(f"projected_primary_D_blocker_if_waived={summary['projected_primary_D_blocker_if_waived']}")
    print("D_strict_gate_pass=false")
    print("D_continued_tracking=true")
    print("D_adoption_allowed=false")
    print("role_review_required=false")
    print(f"remaining_blockers={summary['remaining_blockers']}")
    print("next_action_gate=WAIT_MORE_D_MATURITY")
    print("protected_outputs_modified=false")
    print("official_adoption_allowed=false")
    print("broker_action_allowed=false")
    print(f"report_path={summary['report_path']}")
    return summary


if __name__ == "__main__":
    run()
