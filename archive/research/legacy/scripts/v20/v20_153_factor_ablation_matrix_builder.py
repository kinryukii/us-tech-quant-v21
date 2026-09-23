#!/usr/bin/env python
"""V20.153 factor ablation matrix builder.

Builds a research-only factor ablation matrix from the V20.152 random-as-of
cache layer and optional V20.151 forward-observation outputs. It summarizes
existing evidence only; it does not fabricate factor performance, returns,
outcomes, benchmarks, official weights, official rankings, or trades.
"""

from __future__ import annotations

import csv
import hashlib
import math
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
BACKTEST = OUTPUTS / "backtest"
OBSERVATIONS = OUTPUTS / "observations"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"

IN_CACHE = BACKTEST / "V20_152_RANDOM_AS_OF_BACKTEST_CACHE.csv"
IN_V152_GATE = BACKTEST / "V20_152_RANDOM_AS_OF_BACKTEST_CACHE_GATE.csv"
IN_V152_ELIGIBILITY = BACKTEST / "V20_152_RANDOM_AS_OF_ELIGIBILITY_AUDIT.csv"
IN_V152_SOURCE = BACKTEST / "V20_152_RANDOM_AS_OF_SOURCE_AUDIT.csv"
IN_V151_ACCUMULATION = OBSERVATIONS / "V20_151_FORWARD_OBSERVATION_ACCUMULATION.csv"
IN_V151_ELIGIBILITY = OBSERVATIONS / "V20_151_FORWARD_OBSERVATION_ELIGIBILITY_AUDIT.csv"

OUT_MATRIX = FACTORS / "V20_153_FACTOR_ABLATION_MATRIX.csv"
OUT_GATE = FACTORS / "V20_153_FACTOR_ABLATION_GATE.csv"
OUT_SOURCE_AUDIT = FACTORS / "V20_153_FACTOR_ABLATION_SOURCE_AUDIT.csv"
OUT_ELIGIBILITY_AUDIT = FACTORS / "V20_153_FACTOR_ABLATION_ELIGIBILITY_AUDIT.csv"
OUT_GAP_AUDIT = FACTORS / "V20_153_FACTOR_ABLATION_GAP_AUDIT.csv"
REPORT = READ_CENTER / "V20_153_FACTOR_ABLATION_MATRIX_REPORT.md"

V152_ALLOWED_STATUSES = {
    "PASS_V20_152_RANDOM_AS_OF_BACKTEST_CACHE_READY_FOR_V20_153",
    "PARTIAL_PASS_V20_152_RANDOM_AS_OF_BACKTEST_CACHE_WITH_GAPS_READY_FOR_V20_153",
}
PASS_STATUS = "PASS_V20_153_FACTOR_ABLATION_MATRIX_READY_FOR_V20_154"
PARTIAL_STATUS = "PARTIAL_PASS_V20_153_FACTOR_ABLATION_MATRIX_WITH_LIMITED_EVIDENCE_READY_FOR_V20_154"
WARN_STATUS = "WARN_V20_153_INSUFFICIENT_FACTOR_ABLATION_EVIDENCE"
BLOCKED_STATUS = "BLOCKED_V20_153_FACTOR_ABLATION_MATRIX_BUILDER"
MIN_SHADOW_ASOF_SAMPLES = 4
MIN_SHADOW_OUTCOMES = 4
MIN_SHADOW_BENCHMARKS = 4

SAFETY_FIELDS = [
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
    "official_weight_change_created",
    "weight_mutated",
    "real_book_action_created",
    "trade_action_created",
    "broker_execution_supported",
    "performance_claim_created",
]
SAFETY = {field: "FALSE" for field in SAFETY_FIELDS}
COMMON = {
    **SAFETY,
    "research_only": "TRUE",
    "staging_review_only": "TRUE",
    "factor_ablation_matrix_only": "TRUE",
    "audit_only": "TRUE",
}

MATRIX_FIELDS = [
    "factor_family",
    "factor_name",
    "evidence_source",
    "as_of_sample_count",
    "forward_observation_count",
    "outcome_available_count",
    "pending_outcome_count",
    "benchmark_available_count",
    "positive_contribution_count",
    "negative_contribution_count",
    "neutral_contribution_count",
    "contribution_stability",
    "regime_coverage",
    "window_coverage",
    "usable_for_shadow_weight_proposal",
    "usable_for_official_weight_change",
    "exclusion_reason",
    "evidence_quality",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id",
    "v20_152_gate_consumed",
    "v20_152_status",
    "v20_152_allowed_for_v20_153",
    "staging_review_allowed",
    *SAFETY_FIELDS,
    "source_audit_row_count",
    "matrix_row_count",
    "shadow_weight_research_eligible_count",
    "official_weight_change_eligible_count",
    "pending_outcome_count",
    "gap_count",
    "no_factor_performance_fabricated",
    "no_returns_fabricated",
    "no_outcomes_fabricated",
    "no_benchmarks_fabricated",
    "no_official_weight_change_created",
    "no_official_ranking_mutated",
    "no_upstream_outputs_mutated",
    "v20_154_factor_ablation_review_allowed",
    "next_recommended_action",
    "blocking_reason",
    "final_status",
    "factor_ablation_matrix_status",
    "research_only",
    "staging_review_only",
    "factor_ablation_matrix_only",
    "audit_only",
]
SOURCE_FIELDS = [
    "source_audit_id",
    "source_artifact",
    "source_exists",
    "source_non_empty",
    "row_count",
    "source_sha256",
    "source_role",
    "source_required",
    "source_status",
    "exclusion_reason",
    *COMMON.keys(),
]
ELIGIBILITY_FIELDS = [
    "eligibility_audit_id",
    "factor_family",
    "factor_name",
    "evidence_source",
    "as_of_sample_count",
    "outcome_available_count",
    "benchmark_available_count",
    "pending_outcome_count",
    "eligible_for_shadow_weight_research",
    "eligible_for_official_weight_change",
    "eligibility_status",
    "exclusion_reason",
    "evidence_quality",
    *COMMON.keys(),
]
GAP_FIELDS = [
    "gap_id",
    "factor_family",
    "factor_name",
    "evidence_source",
    "gap_type",
    "gap_reason",
    "repair_action",
    "priority",
    *COMMON.keys(),
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def truthy(value: object) -> bool:
    return clean(value).upper() == "TRUE"


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def resolve_artifact(text: str) -> Path:
    path = Path(text)
    return path if path.is_absolute() else ROOT / path


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists() or path.stat().st_size == 0:
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{key: clean(value) for key, value in row.items()} for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def sha_file(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def upstream_inputs() -> list[Path]:
    return [path for path in [IN_CACHE, IN_V152_GATE, IN_V152_ELIGIBILITY, IN_V152_SOURCE, IN_V151_ACCUMULATION, IN_V151_ELIGIBILITY] if path.exists()]


def upstream_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in upstream_inputs()}


def num(value: object) -> float | None:
    try:
        number = float(clean(value))
    except ValueError:
        return None
    return None if math.isnan(number) or math.isinf(number) else number


def factor_family_for(source: str) -> str:
    text = source.upper()
    if "DOWNSIDE" in text or "RISK" in text:
        return "RISK"
    if "REGIME" in text or "ETF_ROTATION" in text:
        return "MARKET_REGIME"
    if "TECHNICAL" in text or "V20_35" in text:
        return "TECHNICAL"
    if "BENCHMARK" in text:
        return "STRATEGY"
    if "STRATEGY" in text or "MULTI_WINDOW" in text or "V20_91" in text or "V20_82" in text:
        return "STRATEGY"
    if "SCHEMA" in text or "MANIFEST" in text or "COVERAGE" in text:
        return "DATA_TRUST"
    if "FUNDAMENTAL" in text:
        return "FUNDAMENTAL"
    return "DATA_TRUST"


def factor_name_for(source: str) -> str:
    name = Path(source).name.upper()
    if "MULTI_WINDOW_STRATEGY" in name:
        return "MULTI_WINDOW_STRATEGY_EVIDENCE"
    if "DOWNSIDE_RISK" in name:
        return "DOWNSIDE_RISK_EVIDENCE"
    if "REGIME_CONDITIONED" in name:
        return "REGIME_CONDITIONED_EVIDENCE"
    if "BENCHMARK_COMPARISON" in name:
        return "BENCHMARK_COMPARISON_EVIDENCE"
    if "TECHNICAL" in name:
        return "TECHNICAL_RANDOM_AS_OF_EVIDENCE"
    if "ETF_ROTATION" in name:
        return "ETF_ROTATION_EVIDENCE"
    if "EVIDENCE_SCHEMA" in name:
        return "EVIDENCE_SCHEMA_REPAIR"
    stem = re.sub(r"^V20_\d+(_R\d+)?_", "", Path(source).stem.upper())
    return stem[:80] or "UNKNOWN_FACTOR_EVIDENCE"


def contribution_value(row: dict[str, str]) -> float | None:
    for field in [
        "excess_return",
        "alpha_vs_benchmark",
        "benchmark_relative_return_vs_spy",
        "benchmark_relative_return_vs_qqq",
        "risk_adjusted_score",
        "forward_return",
        "ticker_forward_return",
        "strategy_return",
    ]:
        value = num(row.get(field))
        if value is not None:
            return value
    return None


def contribution_counts(source: str) -> tuple[int, int, int]:
    path = resolve_artifact(source)
    rows, _ = read_csv(path)
    pos = neg = neutral = 0
    for row in rows:
        value = contribution_value(row)
        if value is None:
            continue
        if value > 0:
            pos += 1
        elif value < 0:
            neg += 1
        else:
            neutral += 1
    return pos, neg, neutral


def stability(pos: int, neg: int, neutral: int) -> str:
    total = pos + neg + neutral
    if total == 0:
        return "UNKNOWN_NO_FACTOR_CONTRIBUTION_EVIDENCE"
    dominant = max(pos, neg, neutral) / total
    if total >= 10 and dominant >= 0.70:
        return "HIGH"
    if total >= 4 and dominant >= 0.55:
        return "MEDIUM"
    return "LOW"


def quality(asof_count: int, outcome_count: int, benchmark_count: int, pending_count: int, stability_value: str) -> str:
    if asof_count >= MIN_SHADOW_ASOF_SAMPLES and outcome_count >= MIN_SHADOW_OUTCOMES and benchmark_count >= MIN_SHADOW_BENCHMARKS and stability_value in {"HIGH", "MEDIUM"}:
        return "HIGH"
    if asof_count > 0 and (outcome_count > 0 or benchmark_count > 0 or pending_count > 0):
        return "PARTIAL"
    return "INSUFFICIENT"


def source_audit_rows() -> list[dict[str, str]]:
    sources = [
        (IN_CACHE, "V20_152_CACHE", True),
        (IN_V152_GATE, "V20_152_GATE", True),
        (IN_V152_ELIGIBILITY, "V20_152_ELIGIBILITY", True),
        (IN_V152_SOURCE, "V20_152_SOURCE_AUDIT", True),
        (IN_V151_ACCUMULATION, "V20_151_FORWARD_OBSERVATION_ACCUMULATION", False),
        (IN_V151_ELIGIBILITY, "V20_151_FORWARD_OBSERVATION_ELIGIBILITY", False),
    ]
    rows: list[dict[str, str]] = []
    for index, (path, role, required) in enumerate(sources, start=1):
        data, fields = read_csv(path)
        exists = path.exists()
        non_empty = exists and path.stat().st_size > 0
        ok = bool(fields) and (non_empty or not required)
        exclusion = "" if ok else ("MISSING_REQUIRED_SOURCE" if required else "OPTIONAL_SOURCE_MISSING_OR_EMPTY")
        rows.append({
            "source_audit_id": f"V20_153_FACTOR_ABLATION_SOURCE_AUDIT_{index:03d}",
            "source_artifact": rel(path),
            "source_exists": tf(exists),
            "source_non_empty": tf(non_empty),
            "row_count": str(len(data)),
            "source_sha256": sha_file(path),
            "source_role": role,
            "source_required": tf(required),
            "source_status": "PASS" if ok else ("BLOCKED" if required else "WARN"),
            "exclusion_reason": exclusion,
            **COMMON,
        })
    return rows


def build_matrix(cache_rows: list[dict[str, str]], v151_rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in cache_rows:
        source = row.get("source_artifact", "")
        grouped[(factor_family_for(source), factor_name_for(source), source)].append(row)

    forward_observations = len(v151_rows)
    pending_forward = sum(1 for row in v151_rows if row.get("outcome_status") == "OUTCOME_PENDING")
    matrix: list[dict[str, str]] = []
    eligibility: list[dict[str, str]] = []
    gaps: list[dict[str, str]] = []
    for (family, name, source), rows in sorted(grouped.items()):
        asof_count = len({row.get("as_of_date") for row in rows if row.get("as_of_date") and row.get("as_of_date") != "UNKNOWN"})
        window_count = len({row.get("forward_window") for row in rows if row.get("forward_window") and row.get("forward_window") != "UNKNOWN"})
        outcome_count = sum(1 for row in rows if truthy(row.get("outcome_available")))
        benchmark_count = sum(1 for row in rows if truthy(row.get("benchmark_available")))
        pending_count = sum(1 for row in rows if not truthy(row.get("outcome_available")))
        pos, neg, neu = contribution_counts(source)
        stability_value = stability(pos, neg, neu)
        evidence_quality = quality(asof_count, outcome_count, benchmark_count, pending_count + pending_forward, stability_value)
        reasons: list[str] = []
        if asof_count < MIN_SHADOW_ASOF_SAMPLES:
            reasons.append("INSUFFICIENT_AS_OF_SAMPLE_COUNT")
        if outcome_count < MIN_SHADOW_OUTCOMES:
            reasons.append("INSUFFICIENT_OUTCOME_EVIDENCE")
        if benchmark_count < MIN_SHADOW_BENCHMARKS:
            reasons.append("INSUFFICIENT_BENCHMARK_EVIDENCE")
        if stability_value == "UNKNOWN_NO_FACTOR_CONTRIBUTION_EVIDENCE":
            reasons.append("NO_FACTOR_CONTRIBUTION_SIGN_EVIDENCE")
        shadow_ok = not reasons and evidence_quality == "HIGH"
        if shadow_ok:
            exclusion = ""
        else:
            exclusion = "|".join(reasons) if reasons else "LIMITED_EVIDENCE_QUALITY"
        matrix_row = {
            "factor_family": family,
            "factor_name": name,
            "evidence_source": source,
            "as_of_sample_count": str(asof_count),
            "forward_observation_count": str(forward_observations),
            "outcome_available_count": str(outcome_count),
            "pending_outcome_count": str(pending_count + pending_forward),
            "benchmark_available_count": str(benchmark_count),
            "positive_contribution_count": str(pos),
            "negative_contribution_count": str(neg),
            "neutral_contribution_count": str(neu),
            "contribution_stability": stability_value,
            "regime_coverage": "PRESENT" if family == "MARKET_REGIME" and asof_count > 0 else ("REFERENCE_ONLY" if "REGIME" in name else "NOT_APPLICABLE"),
            "window_coverage": str(window_count),
            "usable_for_shadow_weight_proposal": tf(shadow_ok),
            "usable_for_official_weight_change": "FALSE",
            "exclusion_reason": exclusion,
            "evidence_quality": evidence_quality,
            **COMMON,
        }
        matrix.append(matrix_row)
        eligibility.append({
            "eligibility_audit_id": f"V20_153_FACTOR_ABLATION_ELIGIBILITY_AUDIT_{len(eligibility)+1:04d}",
            "factor_family": family,
            "factor_name": name,
            "evidence_source": source,
            "as_of_sample_count": str(asof_count),
            "outcome_available_count": str(outcome_count),
            "benchmark_available_count": str(benchmark_count),
            "pending_outcome_count": str(pending_count + pending_forward),
            "eligible_for_shadow_weight_research": tf(shadow_ok),
            "eligible_for_official_weight_change": "FALSE",
            "eligibility_status": "ELIGIBLE_FOR_SHADOW_WEIGHT_RESEARCH" if shadow_ok else "INSUFFICIENT_EVIDENCE",
            "exclusion_reason": exclusion,
            "evidence_quality": evidence_quality,
            **COMMON,
        })
        for reason in reasons or ([] if shadow_ok else ["LIMITED_EVIDENCE_QUALITY"]):
            gaps.append({
                "gap_id": f"V20_153_FACTOR_ABLATION_GAP_{len(gaps)+1:04d}",
                "factor_family": family,
                "factor_name": name,
                "evidence_source": source,
                "gap_type": reason,
                "gap_reason": reason,
                "repair_action": "Attach additional existing certified factor/outcome/benchmark evidence; do not synthesize factor performance.",
                "priority": "HIGH" if reason in {"INSUFFICIENT_OUTCOME_EVIDENCE", "INSUFFICIENT_BENCHMARK_EVIDENCE"} else "MEDIUM",
                **COMMON,
            })
    return matrix, eligibility, gaps


def safety_true_count(groups: list[list[dict[str, str]]]) -> int:
    return sum(1 for rows in groups for row in rows for field in SAFETY_FIELDS if truthy(row.get(field)))


def write_report(status: str, matrix_count: int, shadow_count: int, gap_count: int) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.153 Factor Ablation Matrix Report",
        "",
        f"- wrapper_status: {status}",
        f"- matrix_row_count: {matrix_count}",
        f"- shadow_weight_research_eligible_count: {shadow_count}",
        f"- gap_count: {gap_count}",
        "- formal_activation_allowed: FALSE",
        "- promotion_ready: FALSE",
        "- official_weight_change_created: FALSE",
        "- performance_claim_created: FALSE",
        "",
        "The matrix is research-only and uses existing V20.152/V20.151 evidence. Pending outcomes and insufficient evidence are retained explicitly; official weight-change eligibility remains FALSE.",
    ]) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_153_FACTOR_ABLATION_GATE_001",
        "v20_152_gate_consumed": "FALSE",
        "v20_152_status": "",
        "v20_152_allowed_for_v20_153": "FALSE",
        "staging_review_allowed": "FALSE",
        **SAFETY,
        "source_audit_row_count": "0",
        "matrix_row_count": "0",
        "shadow_weight_research_eligible_count": "0",
        "official_weight_change_eligible_count": "0",
        "pending_outcome_count": "0",
        "gap_count": "0",
        "no_factor_performance_fabricated": "TRUE",
        "no_returns_fabricated": "TRUE",
        "no_outcomes_fabricated": "TRUE",
        "no_benchmarks_fabricated": "TRUE",
        "no_official_weight_change_created": "TRUE",
        "no_official_ranking_mutated": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "v20_154_factor_ablation_review_allowed": "FALSE",
        "next_recommended_action": "V20.152_RANDOM_AS_OF_BACKTEST_CACHE_REPAIR",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        "factor_ablation_matrix_status": BLOCKED_STATUS,
        "research_only": "TRUE",
        "staging_review_only": "TRUE",
        "factor_ablation_matrix_only": "TRUE",
        "audit_only": "TRUE",
    }
    write_csv(OUT_MATRIX, MATRIX_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SOURCE_AUDIT, SOURCE_FIELDS, [])
    write_csv(OUT_ELIGIBILITY_AUDIT, ELIGIBILITY_FIELDS, [])
    write_csv(OUT_GAP_AUDIT, GAP_FIELDS, [])
    write_report(BLOCKED_STATUS, 0, 0, 0)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    before = upstream_hashes()
    missing_required = [path for path in [IN_CACHE, IN_V152_GATE, IN_V152_ELIGIBILITY, IN_V152_SOURCE] if not path.exists() or path.stat().st_size == 0]
    if missing_required:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing_required))

    gate_rows, _ = read_csv(IN_V152_GATE)
    cache_rows, _ = read_csv(IN_CACHE)
    if not gate_rows or not cache_rows:
        return emit_blocked("EMPTY_V20_152_CACHE_OR_GATE")
    gate_in = gate_rows[0]
    v152_status = clean(gate_in.get("final_status")) or clean(gate_in.get("random_as_of_backtest_cache_status"))
    v152_allowed = v152_status in V152_ALLOWED_STATUSES
    staging_allowed = truthy(gate_in.get("staging_review_allowed"))
    formal_allowed = truthy(gate_in.get("formal_activation_allowed"))
    promotion_ready = truthy(gate_in.get("promotion_ready"))
    if not (v152_allowed and staging_allowed and not formal_allowed and not promotion_ready):
        return emit_blocked("V20_152_GATE_REQUIREMENTS_NOT_MET")

    source_rows = source_audit_rows()
    if any(row["source_required"] == "TRUE" and row["source_status"] == "BLOCKED" for row in source_rows):
        return emit_blocked("REQUIRED_SOURCE_AUDIT_FAILED")

    v151_rows, _ = read_csv(IN_V151_ACCUMULATION)
    matrix_rows, eligibility_rows, gap_rows = build_matrix(cache_rows, v151_rows)
    shadow_count = sum(1 for row in matrix_rows if row["usable_for_shadow_weight_proposal"] == "TRUE")
    official_count = sum(1 for row in matrix_rows if row["usable_for_official_weight_change"] == "TRUE")
    pending_count = sum(int(row.get("pending_outcome_count") or "0") for row in matrix_rows)
    safety_count = safety_true_count([source_rows, matrix_rows, eligibility_rows, gap_rows])
    after = upstream_hashes()
    upstream_mutated = before != after

    if safety_count or official_count or upstream_mutated:
        status = BLOCKED_STATUS
        blocking = "SAFETY_OR_UPSTREAM_MUTATION_FAILURE"
    elif shadow_count > 0 and not gap_rows:
        status = PASS_STATUS
        blocking = ""
    elif shadow_count > 0 or matrix_rows:
        status = PARTIAL_STATUS if shadow_count > 0 else WARN_STATUS
        blocking = ""
    else:
        status = WARN_STATUS
        blocking = ""
    next_allowed = status in {PASS_STATUS, PARTIAL_STATUS}
    gate = {
        "gate_check_id": "V20_153_FACTOR_ABLATION_GATE_001",
        "v20_152_gate_consumed": "TRUE",
        "v20_152_status": v152_status,
        "v20_152_allowed_for_v20_153": tf(v152_allowed),
        "staging_review_allowed": "TRUE",
        **SAFETY,
        "source_audit_row_count": str(len(source_rows)),
        "matrix_row_count": str(len(matrix_rows)),
        "shadow_weight_research_eligible_count": str(shadow_count),
        "official_weight_change_eligible_count": str(official_count),
        "pending_outcome_count": str(pending_count),
        "gap_count": str(len(gap_rows)),
        "no_factor_performance_fabricated": "TRUE",
        "no_returns_fabricated": "TRUE",
        "no_outcomes_fabricated": "TRUE",
        "no_benchmarks_fabricated": "TRUE",
        "no_official_weight_change_created": tf(official_count == 0),
        "no_official_ranking_mutated": "TRUE",
        "no_upstream_outputs_mutated": tf(not upstream_mutated),
        "v20_154_factor_ablation_review_allowed": tf(next_allowed),
        "next_recommended_action": "V20.154_SHADOW_WEIGHT_RESEARCH_REVIEW" if next_allowed else "V20.153_FACTOR_ABLATION_MATRIX_REPAIR",
        "blocking_reason": blocking,
        "final_status": status,
        "factor_ablation_matrix_status": status,
        "research_only": "TRUE",
        "staging_review_only": "TRUE",
        "factor_ablation_matrix_only": "TRUE",
        "audit_only": "TRUE",
    }
    write_csv(OUT_MATRIX, MATRIX_FIELDS, matrix_rows)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SOURCE_AUDIT, SOURCE_FIELDS, source_rows)
    write_csv(OUT_ELIGIBILITY_AUDIT, ELIGIBILITY_FIELDS, eligibility_rows)
    write_csv(OUT_GAP_AUDIT, GAP_FIELDS, gap_rows)
    write_report(status, len(matrix_rows), shadow_count, len(gap_rows))

    print(status)
    print("V20_152_GATE_CONSUMED=TRUE")
    print(f"V20_152_ALLOWED_FOR_V20_153={tf(v152_allowed)}")
    print("STAGING_REVIEW_ALLOWED=TRUE")
    print("FORMAL_ACTIVATION_ALLOWED=FALSE")
    print("PROMOTION_READY=FALSE")
    print(f"MATRIX_ROW_COUNT={len(matrix_rows)}")
    print(f"SHADOW_WEIGHT_RESEARCH_ELIGIBLE_COUNT={shadow_count}")
    print(f"OFFICIAL_WEIGHT_CHANGE_ELIGIBLE_COUNT={official_count}")
    print(f"PENDING_OUTCOME_COUNT={pending_count}")
    print(f"GAP_COUNT={len(gap_rows)}")
    print("FACTOR_PERFORMANCE_FABRICATED=0")
    print("RETURNS_FABRICATED=0")
    print("OUTCOMES_FABRICATED=0")
    print("BENCHMARKS_FABRICATED=0")
    print("OFFICIAL_WEIGHT_CHANGE_CREATED=FALSE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    print(f"SAFETY_TRUE_COUNT={safety_count}")
    print(f"V20_154_FACTOR_ABLATION_REVIEW_ALLOWED={tf(next_allowed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
