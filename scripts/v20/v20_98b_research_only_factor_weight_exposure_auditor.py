#!/usr/bin/env python
"""V20.98B research-only factor weight exposure auditor.

Read-only diagnostic stage. It exposes factor family/context rows and candidate
score source columns currently available to the research-only lane. It does not
create or mutate official weights, recommendations, trade actions, or promotion
state.
"""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
DOC_STATUS = ROOT / "docs" / "v20" / "V20_CURRENT_DEVELOPMENT_STATUS.md"

V48_FACTOR = CONSOLIDATION / "V20_48_REFRESHED_FACTOR_SUPPORT_VIEW.csv"
V50_FACTOR = CONSOLIDATION / "V20_50_FACTOR_RESEARCH_CONTEXT_PACKET.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V50_CANDIDATES = CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

EXPOSURE = CONSOLIDATION / "V20_98B_RESEARCH_ONLY_FACTOR_WEIGHT_EXPOSURE.csv"
SUMMARY = CONSOLIDATION / "V20_98B_FACTOR_FAMILY_WEIGHT_SUMMARY.csv"
CONTRIBUTION = CONSOLIDATION / "V20_98B_FACTOR_SCORE_CONTRIBUTION_AUDIT.csv"
REPORT = READ_CENTER / "V20_98B_RESEARCH_ONLY_FACTOR_WEIGHT_REPORT.md"

EXPOSURE_FIELDS = [
    "factor_family",
    "factor_id",
    "factor_name",
    "source_stage",
    "source_artifact",
    "source_column",
    "base_weight",
    "current_research_weight",
    "normalized_research_weight",
    "effective_research_weight",
    "weight_source_status",
    "used_in_candidate_score",
    "used_in_entry_exit_score",
    "used_in_risk_filter",
    "is_dynamic_weight",
    "is_official_weight",
    "weight_mutated",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "trade_action_created",
    "broker_execution_supported",
]

SUMMARY_FIELDS = [
    "factor_family",
    "factor_count",
    "numeric_weight_count",
    "missing_numeric_weight_count",
    "source_stages",
    "weight_source_status",
    "is_official_weight",
    "weight_mutated",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "trade_action_created",
    "broker_execution_supported",
]

CONTRIBUTION_FIELDS = [
    "source_stage",
    "source_artifact",
    "source_column",
    "row_count",
    "non_empty_count",
    "numeric_count",
    "contribution_source_status",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
]

WEIGHT_COLUMNS = [
    "base_weight",
    "current_research_weight",
    "normalized_research_weight",
    "effective_research_weight",
    "weight",
    "factor_weight",
    "research_weight",
    "normalized_weight",
]

CANDIDATE_SCORE_COLUMNS = [
    "source_rank_or_score",
    "research_priority_band",
    "research_decision_category",
    "evidence_summary",
    "source_contract",
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


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str], str]:
    if not path.exists():
        return [], [], "MISSING"
    if path.stat().st_size == 0:
        return [], [], "EMPTY"
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            rows = [{key: clean(value) for key, value in row.items()} for row in reader]
    except csv.Error:
        return [], [], "MALFORMED"
    return rows, fields, "OK" if fields else "MALFORMED"


def first_row(path: Path) -> dict[str, str]:
    rows, _fields, status = read_csv(path)
    return rows[0] if status == "OK" and rows else {}


def is_float(value: str) -> bool:
    try:
        float(clean(value))
        return bool(clean(value))
    except ValueError:
        return False


def safety() -> dict[str, str]:
    return {
        "is_official_weight": "FALSE",
        "weight_mutated": "FALSE",
        "research_only": "TRUE",
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
    }


def source_stage(path: Path) -> str:
    name = path.name
    if name.startswith("V20_48"):
        return "V20.48"
    if name.startswith("V20_50"):
        return "V20.50"
    return "UNKNOWN"


def discover_weight_columns(row: dict[str, str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for column in WEIGHT_COLUMNS:
        value = clean(row.get(column))
        if value:
            found[column] = value
    return found


def exposure_from_factor_row(path: Path, row: dict[str, str], fallback_index: int) -> dict[str, str]:
    factor_id = clean(row.get("factor_id") or row.get("factor_id_or_name") or f"FACTOR_CONTEXT_{fallback_index:03d}")
    factor_family = clean(row.get("factor_family") or row.get("factor_category") or row.get("report_section") or "UNKNOWN_FACTOR_FAMILY")
    factor_name = clean(row.get("factor_name") or row.get("factor_id_or_name") or factor_id)
    weights = discover_weight_columns(row)
    numeric_weights = {key: value for key, value in weights.items() if is_float(value)}
    weight_status = "NUMERIC_WEIGHT_SOURCE_FOUND" if numeric_weights else "MISSING_NUMERIC_WEIGHT_SOURCE"
    source_column = "|".join(weights.keys()) if weights else "NONE"
    base = clean(row.get("base_weight") or row.get("weight") or row.get("factor_weight"))
    current = clean(row.get("current_research_weight") or row.get("research_weight") or base)
    normalized = clean(row.get("normalized_research_weight") or row.get("normalized_weight"))
    effective = clean(row.get("effective_research_weight") or current)
    if weight_status == "MISSING_NUMERIC_WEIGHT_SOURCE":
        base = current = normalized = effective = ""
    return {
        "factor_family": factor_family,
        "factor_id": factor_id,
        "factor_name": factor_name,
        "source_stage": source_stage(path),
        "source_artifact": rel(path),
        "source_column": source_column,
        "base_weight": base,
        "current_research_weight": current,
        "normalized_research_weight": normalized,
        "effective_research_weight": effective,
        "weight_source_status": weight_status,
        "used_in_candidate_score": tf("factor_score" in factor_family.lower() or "score" in factor_id.lower()),
        "used_in_entry_exit_score": tf("entry" in factor_family.lower() or "exit" in factor_family.lower()),
        "used_in_risk_filter": tf("risk" in factor_family.lower()),
        "is_dynamic_weight": clean(row.get("dynamic_weighting_mutated")).upper() if clean(row.get("dynamic_weighting_mutated")) else "FALSE",
        **safety(),
    }


def build_exposure_rows() -> list[dict[str, str]]:
    rows_out: list[dict[str, str]] = []
    index = 1
    for path in [V48_FACTOR, V50_FACTOR]:
        rows, fields, status = read_csv(path)
        if status == "OK" and rows:
            for row in rows:
                rows_out.append(exposure_from_factor_row(path, row, index))
                index += 1
        elif status == "OK" and fields:
            rows_out.append(
                {
                    "factor_family": "UNKNOWN_FACTOR_FAMILY",
                    "factor_id": f"{source_stage(path)}_FACTOR_SUPPORT_SCHEMA_ONLY",
                    "factor_name": "schema_only_factor_support_view",
                    "source_stage": source_stage(path),
                    "source_artifact": rel(path),
                    "source_column": "NONE",
                    "base_weight": "",
                    "current_research_weight": "",
                    "normalized_research_weight": "",
                    "effective_research_weight": "",
                    "weight_source_status": "MISSING_NUMERIC_WEIGHT_SOURCE",
                    "used_in_candidate_score": "FALSE",
                    "used_in_entry_exit_score": "FALSE",
                    "used_in_risk_filter": "FALSE",
                    "is_dynamic_weight": "FALSE",
                    **safety(),
                }
            )
    if not rows_out:
        rows_out.append(
            {
                "factor_family": "UNKNOWN_FACTOR_FAMILY",
                "factor_id": "NO_FACTOR_CONTEXT_AVAILABLE",
                "factor_name": "no_factor_context_available",
                "source_stage": "V20.98B",
                "source_artifact": "NONE",
                "source_column": "NONE",
                "base_weight": "",
                "current_research_weight": "",
                "normalized_research_weight": "",
                "effective_research_weight": "",
                "weight_source_status": "MISSING_NUMERIC_WEIGHT_SOURCE",
                "used_in_candidate_score": "FALSE",
                "used_in_entry_exit_score": "FALSE",
                "used_in_risk_filter": "FALSE",
                "is_dynamic_weight": "FALSE",
                **safety(),
            }
        )
    return rows_out


def build_summary_rows(exposure_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    families = sorted({row["factor_family"] for row in exposure_rows})
    output: list[dict[str, str]] = []
    for family in families:
        family_rows = [row for row in exposure_rows if row["factor_family"] == family]
        numeric = [row for row in family_rows if row["weight_source_status"] == "NUMERIC_WEIGHT_SOURCE_FOUND"]
        missing = [row for row in family_rows if row["weight_source_status"] == "MISSING_NUMERIC_WEIGHT_SOURCE"]
        output.append(
            {
                "factor_family": family,
                "factor_count": str(len(family_rows)),
                "numeric_weight_count": str(len(numeric)),
                "missing_numeric_weight_count": str(len(missing)),
                "source_stages": "|".join(sorted({row["source_stage"] for row in family_rows})),
                "weight_source_status": "NUMERIC_WEIGHT_SOURCE_FOUND" if numeric else "MISSING_NUMERIC_WEIGHT_SOURCE",
                **safety(),
            }
        )
    return output


def count_non_empty(rows: list[dict[str, str]], column: str) -> int:
    return sum(1 for row in rows if clean(row.get(column)))


def count_numeric(rows: list[dict[str, str]], column: str) -> int:
    return sum(1 for row in rows if is_float(clean(row.get(column))))


def build_contribution_rows() -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for path in [V48_CANDIDATES, V50_CANDIDATES]:
        rows, fields, status = read_csv(path)
        if status != "OK":
            output.append(
                {
                    "source_stage": source_stage(path),
                    "source_artifact": rel(path),
                    "source_column": "NONE",
                    "row_count": "0",
                    "non_empty_count": "0",
                    "numeric_count": "0",
                    "contribution_source_status": status,
                    **safety(),
                }
            )
            continue
        for column in CANDIDATE_SCORE_COLUMNS:
            if column not in fields:
                continue
            numeric_count = count_numeric(rows, column)
            output.append(
                {
                    "source_stage": source_stage(path),
                    "source_artifact": rel(path),
                    "source_column": column,
                    "row_count": str(len(rows)),
                    "non_empty_count": str(count_non_empty(rows, column)),
                    "numeric_count": str(numeric_count),
                    "contribution_source_status": "NUMERIC_SCORE_SOURCE" if numeric_count else "NON_NUMERIC_RESEARCH_CONTEXT_SOURCE",
                    **safety(),
                }
            )
    return output


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_report(exposure_rows: list[dict[str, str]], summary_rows: list[dict[str, str]], contribution_rows: list[dict[str, str]], statuses: dict[str, str]) -> None:
    lines = [
        "# V20.98B Research-Only Factor Weight Exposure Auditor",
        "",
        "## Gate Context",
        f"- v20_49_research_only_gate_status: {statuses['research_status']}",
        f"- v20_49_official_promotion_gate_status: {statuses['official_status']}",
        "- research_only: TRUE",
        "- official_promotion_allowed: FALSE",
        "- official_recommendation_created: FALSE",
        "- weight_mutated: FALSE",
        "- trade_action_created: FALSE",
        "- broker_execution_supported: FALSE",
        "",
        "## Factor Families",
    ]
    for row in summary_rows:
        lines.append(f"- {row['factor_family']}: factors={row['factor_count']}, numeric_weights={row['numeric_weight_count']}, missing_numeric_weights={row['missing_numeric_weight_count']}, status={row['weight_source_status']}")
    lines.extend(["", "## Contribution Sources"])
    for row in contribution_rows:
        lines.append(f"- {row['source_stage']} {row['source_column']}: rows={row['row_count']}, non_empty={row['non_empty_count']}, numeric={row['numeric_count']}, status={row['contribution_source_status']}")
    lines.extend(
        [
            "",
            "No official factor weights are created or mutated by V20.98B. Missing numeric weight sources are explicitly classified and left blank.",
            "",
        ]
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def run() -> dict[str, str]:
    research = first_row(V49_RESEARCH)
    official = first_row(V49_OFFICIAL)
    exposure_rows = build_exposure_rows()
    summary_rows = build_summary_rows(exposure_rows)
    contribution_rows = build_contribution_rows()
    write_csv(EXPOSURE, exposure_rows, EXPOSURE_FIELDS)
    write_csv(SUMMARY, summary_rows, SUMMARY_FIELDS)
    write_csv(CONTRIBUTION, contribution_rows, CONTRIBUTION_FIELDS)
    statuses = {
        "research_status": clean(research.get("research_only_gate_status")),
        "official_status": clean(official.get("official_promotion_gate_status")),
        "factor_family_count": str(len(summary_rows)),
        "missing_numeric_weight_count": str(sum(1 for row in exposure_rows if row["weight_source_status"] == "MISSING_NUMERIC_WEIGHT_SOURCE")),
    }
    write_report(exposure_rows, summary_rows, contribution_rows, statuses)
    return statuses


def main() -> int:
    statuses = run()
    print("PASS_V20_98B_RESEARCH_ONLY_FACTOR_WEIGHT_EXPOSURE_AUDITOR")
    print(f"V20_49_RESEARCH_ONLY_GATE_STATUS={statuses['research_status']}")
    print(f"V20_49_OFFICIAL_PROMOTION_GATE_STATUS={statuses['official_status']}")
    print(f"FACTOR_FAMILY_COUNT={statuses['factor_family_count']}")
    print(f"MISSING_NUMERIC_WEIGHT_COUNT={statuses['missing_numeric_weight_count']}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
