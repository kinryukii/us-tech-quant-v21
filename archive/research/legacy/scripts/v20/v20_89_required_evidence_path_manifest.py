#!/usr/bin/env python
"""V20.89 required evidence path manifest.

This research-only layer declares the evidence paths later promotion checks
must bind before V20.82/V20.84 evidence can be treated as promotion-ready.
It records missing paths as blockers or warnings, but never creates official
recommendations, mutates weights, or creates trade actions.
"""

from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "outputs" / "v20" / "evidence"

PASS_STATUS = "PASS_V20_89_REQUIRED_EVIDENCE_PATH_MANIFEST_CREATED_WITH_BLOCKERS_ALLOWED"

VERSIONED_MANIFEST = OUTPUT_DIR / "V20_89_REQUIRED_EVIDENCE_PATH_MANIFEST.csv"
VERSIONED_SUMMARY = OUTPUT_DIR / "V20_89_REQUIRED_EVIDENCE_PATH_MANIFEST_SUMMARY.md"
CURRENT_MANIFEST = OUTPUT_DIR / "V20_CURRENT_REQUIRED_EVIDENCE_PATH_MANIFEST.csv"
CURRENT_SUMMARY = OUTPUT_DIR / "V20_CURRENT_REQUIRED_EVIDENCE_PATH_MANIFEST_SUMMARY.md"

REQUIRED_COLUMNS = [
    "path_id",
    "evidence_family",
    "required_level",
    "required_for",
    "expected_source_file",
    "expected_current_alias",
    "expected_schema_fields",
    "min_row_count",
    "min_unique_ticker_count",
    "min_benchmark_count",
    "min_regime_count",
    "certification_required",
    "blocking_if_missing",
    "current_status",
    "missing_reason",
    "next_required_stage",
    "research_only",
    "official_recommendation_created",
    "official_weight_mutated",
    "trade_action_created",
]

POSITIVE_CERTIFICATIONS = {
    "CERTIFIED",
    "CERTIFIED_AUTHORITATIVE_OFFICIAL_CURRENT_RESEARCH_RANKING",
    "CERTIFIED_BENCHMARK_COMPARISON_EVIDENCE",
    "CERTIFIED_DOWNSIDE_RISK_EVIDENCE",
    "CERTIFIED_ETF_ROTATION_BACKTEST_EVIDENCE",
    "CERTIFIED_MULTI_PATH_EVIDENCE",
    "CERTIFIED_NASDAQ_HURDLE_EVIDENCE",
    "CERTIFIED_QQQ_COMPARISON_EVIDENCE",
    "CERTIFIED_REGIME_CONDITIONED_EVIDENCE",
}
REJECT_CERT_TOKENS = {
    "BLOCKED",
    "DESIGN_ONLY",
    "INSUFFICIENT",
    "MISSING",
    "NOT_CERTIFIED",
    "NOT_READY",
    "RESEARCH_ONLY_GUARDRAIL",
    "UNCERTIFIED",
}
CERTIFICATION_FIELD_TOKENS = ("certification_status", "certified_flag")


@dataclass(frozen=True)
class EvidencePathSpec:
    path_id: str
    evidence_family: str
    required_level: str
    required_for: str
    expected_source_file: str
    expected_current_alias: str
    expected_schema_fields: tuple[str, ...]
    min_row_count: int
    min_unique_ticker_count: int
    min_benchmark_count: int
    min_regime_count: int
    certification_required: bool
    blocking_if_missing: bool
    next_required_stage: str


DEFAULT_SPECS = [
    EvidencePathSpec(
        "certified_etf_rotation_evidence",
        "etf_rotation",
        "REQUIRED",
        "V20.84/V20.82 promotion validation",
        "outputs/v20/consolidation/V20_84_CERTIFIED_MULTI_PATH_EVIDENCE_TABLE.csv",
        "outputs/v20/consolidation/V20_CURRENT_CERTIFIED_MULTI_PATH_EVIDENCE_TABLE.csv",
        ("ticker", "evidence_path", "certification_status", "research_only"),
        1,
        1,
        0,
        0,
        True,
        True,
        "V20.82_PROMOTION_VALIDATION",
    ),
    EvidencePathSpec(
        "regime_conditioned_evidence",
        "regime",
        "REQUIRED",
        "V20.82 promotion validation",
        "outputs/v20/consolidation/V20_86_REGIME_CONDITIONED_EVIDENCE_EXPORT.csv",
        "outputs/v20/consolidation/V20_CURRENT_REGIME_CONDITIONED_EVIDENCE_EXPORT.csv",
        ("ticker", "regime_bucket", "regime_conditioned_usable_flag", "regime_conditioned_certified_flag"),
        1,
        1,
        0,
        1,
        True,
        True,
        "V20.82_PROMOTION_VALIDATION",
    ),
    EvidencePathSpec(
        "downside_risk_evidence",
        "downside_risk",
        "REQUIRED",
        "V20.82 promotion validation",
        "outputs/v20/consolidation/V20_87_DOWNSIDE_RISK_EVIDENCE_EXPORT.csv",
        "outputs/v20/consolidation/V20_CURRENT_DOWNSIDE_RISK_EVIDENCE_EXPORT.csv",
        ("ticker", "max_drawdown", "downside_risk_usable_flag", "downside_risk_certified_flag"),
        1,
        1,
        0,
        0,
        True,
        True,
        "V20.82_PROMOTION_VALIDATION",
    ),
    EvidencePathSpec(
        "benchmark_comparison_evidence",
        "benchmark_comparison",
        "REQUIRED",
        "V20.82 promotion validation",
        "outputs/v20/consolidation/V20_88_CERTIFIED_BENCHMARK_COMPARISON_EVIDENCE_EXPORT.csv",
        "outputs/v20/consolidation/V20_CURRENT_CERTIFIED_BENCHMARK_COMPARISON_EVIDENCE_EXPORT.csv",
        ("ticker", "benchmark_id", "benchmark_return", "benchmark_comparison_certified_flag"),
        1,
        1,
        1,
        0,
        True,
        True,
        "V20.82_PROMOTION_VALIDATION",
    ),
    EvidencePathSpec(
        "multi_window_strategy_evidence",
        "multi_window_strategy",
        "REQUIRED",
        "V20.82 promotion validation",
        "outputs/v20/consolidation/V20_82_BENCHMARK_STRATEGY_COMPARISON.csv",
        "outputs/v20/consolidation/V20_CURRENT_BENCHMARK_STRATEGY_COMPARISON.csv",
        ("strategy_id", "benchmark_id", "forward_window", "benchmark_return"),
        1,
        0,
        1,
        0,
        False,
        True,
        "V20.82_PROMOTION_VALIDATION",
    ),
    EvidencePathSpec(
        "score_lineage_evidence",
        "score_lineage",
        "REQUIRED",
        "V20.82/V20.84 promotion validation",
        "outputs/v20/consolidation/V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
        "outputs/v20/consolidation/V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
        ("ticker", "rank", "score", "source_stage"),
        1,
        1,
        0,
        0,
        False,
        True,
        "V20.82_PROMOTION_VALIDATION",
    ),
    EvidencePathSpec(
        "ranking_delta_diagnostic_evidence",
        "ranking_delta_diagnostic",
        "OPTIONAL",
        "V20.82 promotion diagnostics",
        "outputs/v20/consolidation/V20_82_CURRENT_VS_SHADOW_MODEL_COMPARISON.csv",
        "outputs/v20/consolidation/V20_CURRENT_CURRENT_VS_SHADOW_MODEL_COMPARISON.csv",
        ("ticker", "current_rank", "shadow_rank", "ranking_delta"),
        1,
        1,
        0,
        0,
        False,
        False,
        "V20.82_DIAGNOSTIC_REVIEW",
    ),
    EvidencePathSpec(
        "acceptance_proof_evidence",
        "acceptance_proof",
        "REQUIRED",
        "V20.82 promotion validation",
        "outputs/v20/consolidation/V20_82_PROMOTION_GATE.csv",
        "outputs/v20/consolidation/V20_CURRENT_PROMOTION_GATE.csv",
        ("gate_id", "gate_status", "blocking_reason"),
        1,
        0,
        0,
        0,
        False,
        True,
        "V20.82_PROMOTION_VALIDATION",
    ),
]


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def read_csv_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def field_value(row: dict[str, str], wanted: str) -> str:
    wanted_lower = wanted.lower()
    for key, value in row.items():
        if key.lower() == wanted_lower:
            return clean(value)
    return ""


def unique_nonempty(rows: list[dict[str, str]], field_names: tuple[str, ...]) -> int:
    values: set[str] = set()
    lowered = {key.lower(): key for row in rows for key in row}
    for field in field_names:
        actual = lowered.get(field.lower())
        if actual:
            values.update(clean(row.get(actual)).upper() for row in rows if clean(row.get(actual)))
            break
    return len(values)


def certification_fields(fieldnames: list[str]) -> list[str]:
    fields: list[str] = []
    for field in fieldnames:
        lower = field.lower()
        if any(token in lower for token in CERTIFICATION_FIELD_TOKENS) and "reason" not in lower and "note" not in lower:
            fields.append(field)
    return fields


def has_structured_positive_certification(rows: list[dict[str, str]], fieldnames: list[str]) -> bool:
    for field in certification_fields(fieldnames):
        for row in rows:
            value = clean(row.get(field)).upper()
            if not value or any(token in value for token in REJECT_CERT_TOKENS):
                continue
            if value in {"TRUE", "1", "YES"} or value in POSITIVE_CERTIFICATIONS or value.startswith("CERTIFIED_"):
                return True
    return False


def notes_only_certification_present(rows: list[dict[str, str]]) -> bool:
    for row in rows:
        for key, value in row.items():
            lower = key.lower()
            text = clean(value).upper()
            if ("note" in lower or "reason" in lower or "explanation" in lower) and "CERTIFIED" in text:
                return True
    return False


def evaluate_spec(spec: EvidencePathSpec, root: Path = ROOT) -> dict[str, str]:
    source = root / spec.expected_source_file
    alias = root / spec.expected_current_alias
    missing_file = not source.exists() or not alias.exists()
    status = "AVAILABLE"
    missing_reason = "NA"

    if missing_file:
        status = "BLOCKED" if spec.blocking_if_missing else "WARN"
        missing_reason = "MISSING_REQUIRED_PATH"
    else:
        try:
            rows, fieldnames = read_csv_rows(source)
        except Exception:
            rows, fieldnames = [], []
            status = "BLOCKED" if spec.blocking_if_missing else "WARN"
            missing_reason = "UNREADABLE_REQUIRED_PATH"

        if missing_reason == "NA":
            lower_fields = {field.lower() for field in fieldnames}
            missing_fields = [field for field in spec.expected_schema_fields if field.lower() not in lower_fields]
            if missing_fields:
                status = "BLOCKED" if spec.blocking_if_missing else "WARN"
                missing_reason = "MISSING_SCHEMA_FIELDS:" + "|".join(missing_fields)
            elif len(rows) < spec.min_row_count:
                status = "BLOCKED" if spec.blocking_if_missing else "WARN"
                missing_reason = "INSUFFICIENT_ROW_COUNT"
            elif unique_nonempty(rows, ("ticker", "symbol")) < spec.min_unique_ticker_count:
                status = "BLOCKED" if spec.blocking_if_missing else "WARN"
                missing_reason = "INSUFFICIENT_UNIQUE_TICKER_COUNT"
            elif unique_nonempty(rows, ("benchmark_id", "benchmark_symbol", "benchmark")) < spec.min_benchmark_count:
                status = "BLOCKED" if spec.blocking_if_missing else "WARN"
                missing_reason = "INSUFFICIENT_BENCHMARK_COUNT"
            elif unique_nonempty(rows, ("regime_bucket", "regime", "market_regime")) < spec.min_regime_count:
                status = "BLOCKED" if spec.blocking_if_missing else "WARN"
                missing_reason = "INSUFFICIENT_REGIME_COUNT"
            elif spec.certification_required and not has_structured_positive_certification(rows, fieldnames):
                status = "BLOCKED" if spec.blocking_if_missing else "WARN"
                missing_reason = "NOTES_ONLY_CERTIFICATION_REJECTED" if notes_only_certification_present(rows) else "STRUCTURED_CERTIFICATION_MISSING"

    return {
        "path_id": spec.path_id,
        "evidence_family": spec.evidence_family,
        "required_level": spec.required_level,
        "required_for": spec.required_for,
        "expected_source_file": spec.expected_source_file,
        "expected_current_alias": spec.expected_current_alias,
        "expected_schema_fields": "|".join(spec.expected_schema_fields),
        "min_row_count": str(spec.min_row_count),
        "min_unique_ticker_count": str(spec.min_unique_ticker_count),
        "min_benchmark_count": str(spec.min_benchmark_count),
        "min_regime_count": str(spec.min_regime_count),
        "certification_required": tf(spec.certification_required),
        "blocking_if_missing": tf(spec.blocking_if_missing),
        "current_status": status,
        "missing_reason": missing_reason,
        "next_required_stage": spec.next_required_stage,
        "research_only": "TRUE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
    }


def build_rows(specs: list[EvidencePathSpec] | None = None, root: Path = ROOT) -> list[dict[str, str]]:
    return [evaluate_spec(spec, root) for spec in (specs or DEFAULT_SPECS)]


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def summary_text(rows: list[dict[str, str]], created_at: str) -> str:
    total = len(rows)
    blocked = sum(1 for row in rows if row["current_status"] == "BLOCKED")
    warn = sum(1 for row in rows if row["current_status"] == "WARN")
    available = sum(1 for row in rows if row["current_status"] == "AVAILABLE")
    required = sum(1 for row in rows if row["required_level"] == "REQUIRED")
    optional = sum(1 for row in rows if row["required_level"] == "OPTIONAL")
    blocker_reasons: dict[str, int] = {}
    for row in rows:
        if row["current_status"] == "BLOCKED":
            blocker_reasons[row["missing_reason"]] = blocker_reasons.get(row["missing_reason"], 0) + 1
    reason_lines = [f"- {reason}: {count}" for reason, count in sorted(blocker_reasons.items())] or ["- none: 0"]
    return "\n".join(
        [
            "# V20.89 Required Evidence Path Manifest Summary",
            "",
            f"- final_status: {PASS_STATUS}",
            f"- created_at_utc: {created_at}",
            f"- required_path_count: {required}",
            f"- optional_path_count: {optional}",
            f"- total_path_count: {total}",
            f"- available_path_count: {available}",
            f"- blocked_path_count: {blocked}",
            f"- warn_path_count: {warn}",
            "- research_only: TRUE",
            "- official_recommendation_created: FALSE",
            "- official_weight_mutated: FALSE",
            "- trade_action_created: FALSE",
            "- blockers_allowed: TRUE",
            "- certification_rule: structured certification fields only; notes text is not certification",
            "",
            "## Blocker Counts",
            *reason_lines,
            "",
        ]
    )


def write_outputs(rows: list[dict[str, str]]) -> None:
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_csv(VERSIONED_MANIFEST, rows)
    VERSIONED_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    VERSIONED_SUMMARY.write_text(summary_text(rows, created_at), encoding="utf-8")
    shutil.copyfile(VERSIONED_MANIFEST, CURRENT_MANIFEST)
    shutil.copyfile(VERSIONED_SUMMARY, CURRENT_SUMMARY)


def main() -> int:
    rows = build_rows()
    write_outputs(rows)
    blocked = sum(1 for row in rows if row["current_status"] == "BLOCKED")
    warn = sum(1 for row in rows if row["current_status"] == "WARN")
    print(PASS_STATUS)
    print(f"required_path_count={len(rows)}")
    print(f"blocked_path_count={blocked}")
    print(f"warn_path_count={warn}")
    print("official_recommendation_created=FALSE")
    print("official_weight_mutated=FALSE")
    print("trade_action_created=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
