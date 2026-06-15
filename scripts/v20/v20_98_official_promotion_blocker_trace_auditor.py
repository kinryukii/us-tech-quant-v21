#!/usr/bin/env python
"""V20.98 official promotion blocker trace auditor.

Read-only diagnostic stage. It traces why V20.49 official promotion remains
blocked after V20.54 and the research-only gate are ready. It does not mutate
upstream gates or create recommendation/trading artifacts.
"""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

TRACE = CONSOLIDATION / "V20_98_OFFICIAL_PROMOTION_BLOCKER_TRACE.csv"
LINEAGE_AUDIT = CONSOLIDATION / "V20_98_PROMOTION_LINEAGE_SOURCE_AUDIT.csv"
COUNT_AUDIT = CONSOLIDATION / "V20_98_CANDIDATE_COUNT_CONTRACT_AUDIT.csv"
OPTIONALITY_AUDIT = CONSOLIDATION / "V20_98_V20_52_53_OPTIONALITY_AUDIT.csv"
REPORT = READ_CENTER / "V20_98_OFFICIAL_PROMOTION_BLOCKER_TRACE_REPORT.md"

V20_54_REPORT = READ_CENTER / "V20_54_USER_READABLE_CURRENT_DECISION_REPORT.md"
V20_49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"
V20_49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V20_48_SUMMARY = CONSOLIDATION / "V20_48_REFRESHED_OPERATOR_REPORT_SUMMARY.csv"
V20_48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V20_49_CANDIDATES = CONSOLIDATION / "V20_49_OPERATOR_CANDIDATE_REVIEW_READINESS.csv"
V20_50_CANDIDATES = CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"

REQUIRED_BLOCKERS = [
    "formal_tests_failed",
    "candidate_refreshed_count_mismatch",
    "lineage_contract_validation_failed",
    "v20_27_missing_pit_safe_active_outcome_benchmark_staged_inputs",
    "upstream_v20_48_tests_status_fail",
    "missing_promotion_lineage_sources",
]

REQUIRED_LINEAGE_SOURCES = [
    "V20.35-R2",
    "V20.36",
    "V20.37",
    "V20.38",
    "V20.39",
    "V20.40",
    "V20.41",
    "V20.42",
]

OPTIONAL_OFFICIAL_ARTIFACTS = [
    ("V20.52", CONSOLIDATION / "V20_52_NEXT_STEP_DECISION.csv"),
    ("V20.52", CONSOLIDATION / "V20_52_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_GATE.csv"),
    ("V20.53", CONSOLIDATION / "V20_53_NEXT_STEP_DECISION.csv"),
    ("V20.53", CONSOLIDATION / "V20_53_OFFICIAL_RECOMMENDATION_SCHEMA_DRY_RUN_GATE.csv"),
]

TRACE_FIELDS = [
    "blocker_id",
    "blocker_present",
    "source_artifact_path",
    "source_field",
    "source_value",
    "diagnostic",
    "resolution_hint",
    "research_only_allowed",
    "official_promotion_allowed",
    "official_recommendation_created",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
]

LINEAGE_FIELDS = [
    "lineage_source",
    "official_gate_lists_missing",
    "source_artifacts_found_count",
    "source_artifacts_found",
    "lineage_contract_status",
    "research_only_allowed",
    "official_promotion_allowed",
    "official_recommendation_created",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
]

COUNT_FIELDS = [
    "source_stage",
    "source_artifact_path",
    "exists_non_empty",
    "row_count",
    "reported_candidate_count",
    "candidate_count_contract_status",
    "notes",
    "research_only_allowed",
    "official_promotion_allowed",
    "official_recommendation_created",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
]

OPTIONALITY_FIELDS = [
    "stage",
    "artifact_path",
    "exists_non_empty",
    "status_field",
    "status_value",
    "official_promotion_evidence_classification",
    "notes",
    "research_only_allowed",
    "official_promotion_allowed",
    "official_recommendation_created",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], str]:
    if not path.exists():
        return [], "MISSING"
    if path.stat().st_size == 0:
        return [], "EMPTY"
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = [{key: clean(value) for key, value in row.items()} for row in reader]
    except csv.Error:
        return [], "MALFORMED"
    return rows, "OK" if reader.fieldnames else "MALFORMED"


def first_row(path: Path) -> dict[str, str]:
    rows, status = read_csv(path)
    return rows[0] if status == "OK" and rows else {}


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def safety_fields(research_only_gate_status: str, official_gate_status: str) -> dict[str, str]:
    return {
        "research_only_allowed": tf(research_only_gate_status == "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE"),
        "official_promotion_allowed": tf(official_gate_status == "PASS_V20_49_OFFICIAL_PROMOTION_GATE"),
        "official_recommendation_created": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
    }


def file_exists_non_empty(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def build_trace(official: dict[str, str], research: dict[str, str], v54_pass: bool) -> list[dict[str, str]]:
    official_status = clean(official.get("official_promotion_gate_status"))
    research_status = clean(research.get("research_only_gate_status"))
    safety = safety_fields(research_status, official_status)
    blocker_text = clean(official.get("official_promotion_blockers"))
    present = set(item for item in blocker_text.split(";") if item)
    diagnostics = {
        "formal_tests_failed": clean(official.get("acceptance_status")) or "formal test status is included in V20.49 blockers",
        "candidate_refreshed_count_mismatch": f"lineage_rows_available={clean(official.get('lineage_rows_available'))}; minimum_required_lineage_rows={clean(official.get('minimum_required_lineage_rows'))}",
        "lineage_contract_validation_failed": f"missing_promotion_lineage_sources={clean(official.get('missing_promotion_lineage_sources'))}",
        "v20_27_missing_pit_safe_active_outcome_benchmark_staged_inputs": clean(official.get("v20_27_blocker")) or clean(official.get("v20_27_status")),
        "upstream_v20_48_tests_status_fail": clean(official.get("upstream_v20_48_tests_status")),
        "missing_promotion_lineage_sources": clean(official.get("missing_promotion_lineage_sources")),
    }
    hints = {
        "formal_tests_failed": "Repair formal tests and operator acceptance separately; do not infer official promotion from V20.54 PASS.",
        "candidate_refreshed_count_mismatch": "Reconcile refreshed candidate and lineage contract counts before promotion.",
        "lineage_contract_validation_failed": "Repair lineage contract coverage and validation rows.",
        "v20_27_missing_pit_safe_active_outcome_benchmark_staged_inputs": "Wait for PIT-safe forward target dates or import authoritative PIT-safe outcome/benchmark rows with provenance.",
        "upstream_v20_48_tests_status_fail": "Repair upstream V20.48 formal test status before official promotion.",
        "missing_promotion_lineage_sources": "Provide required V20.35-R2 through V20.42 promotion lineage evidence.",
    }
    rows: list[dict[str, str]] = []
    for blocker in REQUIRED_BLOCKERS:
        row = {
            "blocker_id": blocker,
            "blocker_present": tf(blocker in present),
            "source_artifact_path": rel(V20_49_OFFICIAL),
            "source_field": "official_promotion_blockers",
            "source_value": blocker_text,
            "diagnostic": diagnostics[blocker],
            "resolution_hint": hints[blocker],
            **safety,
        }
        rows.append(row)
    rows.append(
        {
            "blocker_id": "context_v20_54_pass_recognized",
            "blocker_present": tf(v54_pass),
            "source_artifact_path": rel(V20_54_REPORT),
            "source_field": "Status",
            "source_value": "PASS_V20_54_USER_READABLE_CURRENT_DECISION_REPORT" if v54_pass else "NOT_RECOGNIZED",
            "diagnostic": "V20.54 user-readable report PASS is recognized as research/readable readiness only.",
            "resolution_hint": "V20.54 PASS does not override V20.49 official promotion blockers.",
            **safety,
        }
    )
    return rows


def lineage_glob(source: str) -> list[Path]:
    token = source.replace(".", "_").replace("-", "_").upper()
    return sorted(CONSOLIDATION.glob(f"{token}*.csv"))


def build_lineage_audit(official: dict[str, str], research_status: str) -> list[dict[str, str]]:
    official_status = clean(official.get("official_promotion_gate_status"))
    safety = safety_fields(research_status, official_status)
    missing = set(clean(official.get("missing_promotion_lineage_sources")).split(";"))
    rows: list[dict[str, str]] = []
    for source in REQUIRED_LINEAGE_SOURCES:
        found = lineage_glob(source)
        rows.append(
            {
                "lineage_source": source,
                "official_gate_lists_missing": tf(source in missing),
                "source_artifacts_found_count": str(len(found)),
                "source_artifacts_found": "|".join(rel(path) for path in found) if found else "NONE",
                "lineage_contract_status": "MISSING_FOR_PROMOTION" if source in missing else "NOT_LISTED_MISSING_BY_V20_49",
                **safety,
            }
        )
    return rows


def candidate_count_row(stage: str, path: Path, reported: str, notes: str, safety: dict[str, str]) -> dict[str, str]:
    rows, status = read_csv(path)
    exists = status == "OK"
    row_count = len(rows) if status == "OK" else 0
    contract = "SOURCE_AVAILABLE"
    if not exists:
        contract = status
    elif reported and reported.isdigit() and int(reported) != row_count:
        contract = "COUNT_MISMATCH_REPORTED_VS_ROWS"
    return {
        "source_stage": stage,
        "source_artifact_path": rel(path),
        "exists_non_empty": tf(file_exists_non_empty(path)),
        "row_count": str(row_count),
        "reported_candidate_count": reported or "NA",
        "candidate_count_contract_status": contract,
        "notes": notes,
        **safety,
    }


def build_candidate_count_audit(official: dict[str, str], research: dict[str, str], v48: dict[str, str]) -> list[dict[str, str]]:
    safety = safety_fields(clean(research.get("research_only_gate_status")), clean(official.get("official_promotion_gate_status")))
    return [
        candidate_count_row("V20.48", V20_48_CANDIDATES, clean(v48.get("candidate_research_rows_input")), "refreshed candidate research view", safety),
        candidate_count_row("V20.49", V20_49_CANDIDATES, clean(research.get("active_candidate_rows_available")), "operator candidate review readiness", safety),
        candidate_count_row("V20.50", V20_50_CANDIDATES, "", "research-only candidate decision packet", safety),
    ]


def build_optionality_audit(official: dict[str, str], research_status: str) -> list[dict[str, str]]:
    safety = safety_fields(research_status, clean(official.get("official_promotion_gate_status")))
    rows: list[dict[str, str]] = []
    for stage, path in OPTIONAL_OFFICIAL_ARTIFACTS:
        first = first_row(path)
        status_value = clean(first.get("STATUS") or first.get("status") or first.get("decision"))
        exists = file_exists_non_empty(path)
        classification = "OPTIONAL_OFFICIAL_ARTIFACT_MISSING_NOT_PROMOTION_EVIDENCE"
        if exists:
            classification = "OPTIONAL_OFFICIAL_ARTIFACT_PRESENT_NOT_SUFFICIENT_FOR_PROMOTION" if not status_value.startswith("PASS") else "OPTIONAL_OFFICIAL_ARTIFACT_PASS_STILL_SUBORDINATE_TO_V20_49_GATE"
        rows.append(
            {
                "stage": stage,
                "artifact_path": rel(path),
                "exists_non_empty": tf(exists),
                "status_field": "STATUS/status/decision",
                "status_value": status_value or "NA",
                "official_promotion_evidence_classification": classification,
                "notes": "V20.52/V20.53 optional artifacts must not be treated as successful official promotion evidence unless V20.49 official promotion gate passes.",
                **safety,
            }
        )
    return rows


def write_report(trace_rows: list[dict[str, str]], lineage_rows: list[dict[str, str]], count_rows: list[dict[str, str]], optional_rows: list[dict[str, str]], statuses: dict[str, str]) -> None:
    blockers = [row["blocker_id"] for row in trace_rows if row["blocker_id"] in REQUIRED_BLOCKERS and row["blocker_present"] == "TRUE"]
    lines = [
        "# V20.98 Official Promotion Blocker Trace Auditor",
        "",
        "## Gate Status",
        f"- v20_54_status: {statuses['v20_54_status']}",
        f"- v20_49_research_only_gate_status: {statuses['v20_49_research_only_gate_status']}",
        f"- v20_49_official_promotion_gate_status: {statuses['v20_49_official_promotion_gate_status']}",
        f"- official_promotion_allowed: {statuses['official_promotion_allowed']}",
        "",
        "## Blockers",
        f"- blocker_ids: {';'.join(blockers)}",
        f"- missing_promotion_lineage_sources: {';'.join(row['lineage_source'] for row in lineage_rows if row['official_gate_lists_missing'] == 'TRUE')}",
        "",
        "## Candidate Count Sources",
    ]
    for row in count_rows:
        lines.append(f"- {row['source_stage']}: rows={row['row_count']}, reported={row['reported_candidate_count']}, status={row['candidate_count_contract_status']}")
    lines.extend(
        [
            "",
            "## V20.52 / V20.53 Optionality",
        ]
    )
    for row in optional_rows:
        lines.append(f"- {row['stage']} {row['artifact_path']}: exists_non_empty={row['exists_non_empty']}, classification={row['official_promotion_evidence_classification']}")
    lines.extend(
        [
            "",
            "## Safety",
            "- research_only_allowed: TRUE",
            "- official_promotion_allowed: FALSE",
            "- official_recommendation_created: FALSE",
            "- weight_mutated: FALSE",
            "- trade_action_created: FALSE",
            "- broker_execution_supported: FALSE",
            "",
            "V20.98 is diagnostic only. It does not mutate V20.27, V20.49, V20.54, or upstream gates.",
            "",
        ]
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def run() -> dict[str, str]:
    official = first_row(V20_49_OFFICIAL)
    research = first_row(V20_49_RESEARCH)
    v48 = first_row(V20_48_SUMMARY)
    v54_text = V20_54_REPORT.read_text(encoding="utf-8", errors="ignore") if V20_54_REPORT.exists() else ""
    v54_pass = "PASS_V20_54_USER_READABLE_CURRENT_DECISION_REPORT" in v54_text
    trace_rows = build_trace(official, research, v54_pass)
    lineage_rows = build_lineage_audit(official, clean(research.get("research_only_gate_status")))
    count_rows = build_candidate_count_audit(official, research, v48)
    optional_rows = build_optionality_audit(official, clean(research.get("research_only_gate_status")))
    write_csv(TRACE, trace_rows, TRACE_FIELDS)
    write_csv(LINEAGE_AUDIT, lineage_rows, LINEAGE_FIELDS)
    write_csv(COUNT_AUDIT, count_rows, COUNT_FIELDS)
    write_csv(OPTIONALITY_AUDIT, optional_rows, OPTIONALITY_FIELDS)
    statuses = {
        "v20_54_status": "PASS_V20_54_USER_READABLE_CURRENT_DECISION_REPORT" if v54_pass else "NOT_RECOGNIZED",
        "v20_49_research_only_gate_status": clean(research.get("research_only_gate_status")),
        "v20_49_official_promotion_gate_status": clean(official.get("official_promotion_gate_status")),
        "official_promotion_allowed": "FALSE" if clean(official.get("official_promotion_gate_status")) != "PASS_V20_49_OFFICIAL_PROMOTION_GATE" else "TRUE",
    }
    write_report(trace_rows, lineage_rows, count_rows, optional_rows, statuses)
    return statuses


def main() -> int:
    statuses = run()
    print("PASS_V20_98_OFFICIAL_PROMOTION_BLOCKER_TRACE_AUDITOR")
    for key, value in statuses.items():
        print(f"{key.upper()}={value}")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
