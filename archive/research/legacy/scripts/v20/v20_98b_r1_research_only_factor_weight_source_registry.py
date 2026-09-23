#!/usr/bin/env python
"""V20.98B-R1 research-only factor weight source registry.

Builds a canonical registry and gap audit for research-only factor weight
sources after V20.98B found missing numeric weight inputs. This is read-only
and never fabricates weights from scores or rank order.
"""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

EXPOSURE_IN = CONSOLIDATION / "V20_98B_RESEARCH_ONLY_FACTOR_WEIGHT_EXPOSURE.csv"
SUMMARY_IN = CONSOLIDATION / "V20_98B_FACTOR_FAMILY_WEIGHT_SUMMARY.csv"
CONTRIBUTION_IN = CONSOLIDATION / "V20_98B_FACTOR_SCORE_CONTRIBUTION_AUDIT.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

REGISTRY = CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv"
GAP_AUDIT = CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_GAP_AUDIT.csv"
COLUMN_MAP = CONSOLIDATION / "V20_98B_R1_FACTOR_COLUMN_TO_FAMILY_MAP.csv"
REPORT = READ_CENTER / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY_REPORT.md"

EXPLICIT_WEIGHT_COLUMNS = {
    "base_weight",
    "current_research_weight",
    "normalized_research_weight",
    "effective_research_weight",
    "weight",
    "factor_weight",
    "research_weight",
    "normalized_weight",
}

REGISTRY_FIELDS = [
    "factor_family",
    "factor_id",
    "factor_name",
    "source_stage",
    "source_artifact",
    "source_column",
    "source_column_role",
    "explicit_weight_column",
    "numeric_source_available",
    "base_weight",
    "current_research_weight",
    "normalized_research_weight",
    "effective_research_weight",
    "weight_source_status",
    "base_weight_gap",
    "downstream_blocker_v20_107",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "is_official_weight",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
]

GAP_FIELDS = [
    "gap_id",
    "factor_family",
    "factor_id",
    "gap_status",
    "gap_reason",
    "required_source",
    "downstream_blocker",
    "resolution_hint",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "is_official_weight",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
]

COLUMN_MAP_FIELDS = [
    "source_stage",
    "source_artifact",
    "source_column",
    "mapped_factor_family",
    "factor_role",
    "numeric_count",
    "is_explicit_weight_column",
    "is_candidate_score_source",
    "is_factor_weight_source",
    "classification",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "is_official_weight",
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


def is_numeric(value: str) -> bool:
    try:
        float(clean(value))
        return bool(clean(value))
    except ValueError:
        return False


def safety() -> dict[str, str]:
    return {
        "research_only": "TRUE",
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "is_official_weight": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
    }


def source_column_role(source_column: str) -> str:
    col = clean(source_column)
    if not col or col == "NONE":
        return "NO_EXPLICIT_SOURCE_COLUMN"
    if col in EXPLICIT_WEIGHT_COLUMNS:
        return "EXPLICIT_WEIGHT_COLUMN"
    if col == "source_rank_or_score":
        return "CANDIDATE_SCORE_SOURCE"
    if "score" in col.lower():
        return "SCORE_OR_CONTEXT_SOURCE_NOT_WEIGHT"
    return "RESEARCH_CONTEXT_SOURCE_NOT_WEIGHT"


def build_registry(exposure_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for row in exposure_rows:
        columns = [col for col in clean(row.get("source_column")).split("|") if col] or ["NONE"]
        explicit_columns = [col for col in columns if col in EXPLICIT_WEIGHT_COLUMNS]
        numeric_weight = any(is_numeric(row.get(field, "")) for field in ["base_weight", "current_research_weight", "normalized_research_weight", "effective_research_weight"])
        for column in columns:
            explicit = column in EXPLICIT_WEIGHT_COLUMNS
            missing = not (explicit and numeric_weight)
            output.append(
                {
                    "factor_family": clean(row.get("factor_family")) or "UNKNOWN_FACTOR_FAMILY",
                    "factor_id": clean(row.get("factor_id")) or "UNKNOWN_FACTOR",
                    "factor_name": clean(row.get("factor_name")) or clean(row.get("factor_id")) or "UNKNOWN_FACTOR",
                    "source_stage": clean(row.get("source_stage")),
                    "source_artifact": clean(row.get("source_artifact")),
                    "source_column": column,
                    "source_column_role": source_column_role(column),
                    "explicit_weight_column": tf(explicit),
                    "numeric_source_available": tf(numeric_weight and explicit),
                    "base_weight": clean(row.get("base_weight")) if explicit and numeric_weight else "",
                    "current_research_weight": clean(row.get("current_research_weight")) if explicit and numeric_weight else "",
                    "normalized_research_weight": clean(row.get("normalized_research_weight")) if explicit and numeric_weight else "",
                    "effective_research_weight": clean(row.get("effective_research_weight")) if explicit and numeric_weight else "",
                    "weight_source_status": "NUMERIC_WEIGHT_SOURCE_FOUND" if explicit and numeric_weight else "MISSING_NUMERIC_WEIGHT_SOURCE",
                    "base_weight_gap": tf(missing),
                    "downstream_blocker_v20_107": tf(missing),
                    **safety(),
                }
            )
        if not explicit_columns and not columns:
            continue
    return output


def build_gap_audit(registry_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for row in registry_rows:
        if row["base_weight_gap"] != "TRUE":
            continue
        output.append(
            {
                "gap_id": f"BASE_WEIGHT_SOURCE_GAP::{row['factor_id']}::{row['source_column']}",
                "factor_family": row["factor_family"],
                "factor_id": row["factor_id"],
                "gap_status": "MISSING_BASE_WEIGHT_SOURCE",
                "gap_reason": "No explicit numeric base_weight/current_research_weight/effective_research_weight source exists; candidate score columns are not weights.",
                "required_source": "authoritative research-only numeric factor weight source with provenance",
                "downstream_blocker": "V20.107_SHADOW_DYNAMIC_REWEIGHTING_BLOCKED_UNTIL_BASE_WEIGHT_SOURCE_EXISTS",
                "resolution_hint": "Add a provenance-backed research-only factor weight source registry; do not infer weights from rank order or source scores.",
                **safety(),
            }
        )
    return output


def infer_family_from_column(column: str) -> str:
    col = column.lower()
    if "rank" in col or "score" in col:
        return "candidate_score_context"
    if "priority" in col or "decision" in col:
        return "research_decision_context"
    if "contract" in col or "evidence" in col:
        return "research_context"
    return "UNKNOWN_FACTOR_FAMILY"


def build_column_map(contribution_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for row in contribution_rows:
        column = clean(row.get("source_column"))
        explicit = column in EXPLICIT_WEIGHT_COLUMNS
        candidate_score = clean(row.get("contribution_source_status")) == "NUMERIC_SCORE_SOURCE" or column == "source_rank_or_score"
        classification = "EXPLICIT_FACTOR_WEIGHT_SOURCE" if explicit else ("CANDIDATE_SCORE_SOURCE_NOT_FACTOR_WEIGHT" if candidate_score else "RESEARCH_CONTEXT_SOURCE_NOT_FACTOR_WEIGHT")
        output.append(
            {
                "source_stage": clean(row.get("source_stage")),
                "source_artifact": clean(row.get("source_artifact")),
                "source_column": column,
                "mapped_factor_family": infer_family_from_column(column),
                "factor_role": source_column_role(column),
                "numeric_count": clean(row.get("numeric_count")) or "0",
                "is_explicit_weight_column": tf(explicit),
                "is_candidate_score_source": tf(candidate_score),
                "is_factor_weight_source": tf(explicit),
                "classification": classification,
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


def write_report(registry_rows: list[dict[str, str]], gap_rows: list[dict[str, str]], map_rows: list[dict[str, str]], statuses: dict[str, str]) -> None:
    lines = [
        "# V20.98B-R1 Factor Weight Source Registry",
        "",
        "## Gate Context",
        f"- v20_49_research_only_gate_status: {statuses['research_status']}",
        f"- v20_49_official_promotion_gate_status: {statuses['official_status']}",
        "- research_only: TRUE",
        "- official_promotion_allowed: FALSE",
        "- official_recommendation_created: FALSE",
        "- is_official_weight: FALSE",
        "- weight_mutated: FALSE",
        "- trade_action_created: FALSE",
        "- broker_execution_supported: FALSE",
        "",
        "## Registry Counts",
        f"- registry_row_count: {len(registry_rows)}",
        f"- base_weight_gap_count: {len(gap_rows)}",
        f"- column_map_row_count: {len(map_rows)}",
        "",
        "## Downstream Blocker",
        "- V20.107 shadow dynamic reweighting cannot run until an authoritative base_weight source exists.",
        "",
        "## Column Classification",
    ]
    for row in map_rows:
        lines.append(f"- {row['source_stage']} {row['source_column']}: {row['classification']}")
    lines.extend(
        [
            "",
            "No numeric factor weights are fabricated. Candidate score columns, including source_rank_or_score, are audited as score sources and not factor weights.",
            "",
        ]
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def run() -> dict[str, str]:
    exposure_rows, _fields, _status = read_csv(EXPOSURE_IN)
    contribution_rows, _fields2, _status2 = read_csv(CONTRIBUTION_IN)
    research = first_row(V49_RESEARCH)
    official = first_row(V49_OFFICIAL)
    registry_rows = build_registry(exposure_rows)
    gap_rows = build_gap_audit(registry_rows)
    map_rows = build_column_map(contribution_rows)
    write_csv(REGISTRY, registry_rows, REGISTRY_FIELDS)
    write_csv(GAP_AUDIT, gap_rows, GAP_FIELDS)
    write_csv(COLUMN_MAP, map_rows, COLUMN_MAP_FIELDS)
    statuses = {
        "research_status": clean(research.get("research_only_gate_status")),
        "official_status": clean(official.get("official_promotion_gate_status")),
        "registry_row_count": str(len(registry_rows)),
        "base_weight_gap_count": str(len(gap_rows)),
    }
    write_report(registry_rows, gap_rows, map_rows, statuses)
    return statuses


def main() -> int:
    statuses = run()
    print("PASS_V20_98B_R1_RESEARCH_ONLY_FACTOR_WEIGHT_SOURCE_REGISTRY")
    print(f"V20_49_RESEARCH_ONLY_GATE_STATUS={statuses['research_status']}")
    print(f"V20_49_OFFICIAL_PROMOTION_GATE_STATUS={statuses['official_status']}")
    print(f"REGISTRY_ROW_COUNT={statuses['registry_row_count']}")
    print(f"BASE_WEIGHT_GAP_COUNT={statuses['base_weight_gap_count']}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("IS_OFFICIAL_WEIGHT=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
