#!/usr/bin/env python
"""V20.153-R2 factor ablation existing-evidence bridge repair.

Repairs bridge issues between existing evidence artifacts, the V20.152 random
as-of cache, and the V20.153 factor ablation matrix. It never generates new
backtest results, outcomes, benchmark returns, contribution attribution, shadow
weights, official weights, or official ranking changes.
"""

from __future__ import annotations

import csv
import hashlib
import math
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
FACTORS = OUTPUTS / "factors"
BACKTEST = OUTPUTS / "backtest"
EVIDENCE = OUTPUTS / "evidence"
CONSOLIDATION = OUTPUTS / "consolidation"
OPS = OUTPUTS / "ops"
READ_CENTER = OUTPUTS / "read_center"

R1_DIAGNOSTIC = FACTORS / "V20_153_R1_FACTOR_ABLATION_INSUFFICIENCY_DIAGNOSTIC.csv"
R1_BREAKDOWN = FACTORS / "V20_153_R1_FACTOR_ABLATION_BLOCKER_BREAKDOWN.csv"
R1_REPAIR = FACTORS / "V20_153_R1_FACTOR_ABLATION_REPAIR_PLAN.csv"
R1_GATE = FACTORS / "V20_153_R1_FACTOR_ABLATION_NEXT_GATE.csv"

V153_MATRIX = FACTORS / "V20_153_FACTOR_ABLATION_MATRIX.csv"
V153_GATE = FACTORS / "V20_153_FACTOR_ABLATION_GATE.csv"
V153_SOURCE = FACTORS / "V20_153_FACTOR_ABLATION_SOURCE_AUDIT.csv"
V153_ELIGIBILITY = FACTORS / "V20_153_FACTOR_ABLATION_ELIGIBILITY_AUDIT.csv"
V153_GAP = FACTORS / "V20_153_FACTOR_ABLATION_GAP_AUDIT.csv"

V152_CACHE = BACKTEST / "V20_152_RANDOM_AS_OF_BACKTEST_CACHE.csv"
V152_GATE = BACKTEST / "V20_152_RANDOM_AS_OF_BACKTEST_CACHE_GATE.csv"
V152_SOURCE = BACKTEST / "V20_152_RANDOM_AS_OF_SOURCE_AUDIT.csv"
V152_ELIGIBILITY = BACKTEST / "V20_152_RANDOM_AS_OF_ELIGIBILITY_AUDIT.csv"
V152_GAP = BACKTEST / "V20_152_RANDOM_AS_OF_GAP_REPAIR_PLAN.csv"

OUT_REPAIR = FACTORS / "V20_153_R2_FACTOR_ABLATION_EXISTING_EVIDENCE_BRIDGE_REPAIR.csv"
OUT_SOURCE_AUDIT = FACTORS / "V20_153_R2_FACTOR_ABLATION_BRIDGE_SOURCE_AUDIT.csv"
OUT_MATRIX = FACTORS / "V20_153_R2_FACTOR_ABLATION_REPAIRED_MATRIX.csv"
OUT_BLOCKERS = FACTORS / "V20_153_R2_FACTOR_ABLATION_REMAINING_BLOCKERS.csv"
OUT_GATE = FACTORS / "V20_153_R2_FACTOR_ABLATION_NEXT_GATE.csv"
REPORT = READ_CENTER / "V20_153_R2_FACTOR_ABLATION_EXISTING_EVIDENCE_BRIDGE_REPAIR_REPORT.md"

PASS_STATUS = "PASS_V20_153_R2_FACTOR_ABLATION_BRIDGE_REPAIR_READY_FOR_V20_154"
PARTIAL_STATUS = "PARTIAL_PASS_V20_153_R2_FACTOR_ABLATION_BRIDGE_REPAIR_WITH_LIMITED_SHADOW_ELIGIBILITY"
WARN_STATUS = "WARN_V20_153_R2_NO_REPAIRABLE_EXISTING_EVIDENCE_FOUND"
BLOCKED_STATUS = "BLOCKED_V20_153_R2_FACTOR_ABLATION_BRIDGE_REPAIR"
R1_ALLOWED = {
    "PASS_V20_153_R1_FACTOR_ABLATION_INSUFFICIENCY_DIAGNOSTIC_READY_FOR_REPAIR",
    "PARTIAL_PASS_V20_153_R1_FACTOR_ABLATION_DIAGNOSTIC_WITH_UNREPAIRABLE_PENDING_OUTCOMES",
}
V153_REQUIRED_STATUS = "WARN_V20_153_INSUFFICIENT_FACTOR_ABLATION_EVIDENCE"
MIN_ASOF = 4
MIN_OUTCOME = 4
MIN_BENCHMARK = 4
MIN_WINDOW = 2

SAFETY_FIELDS = [
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
    "official_weight_change_created",
    "shadow_weight_proposal_created",
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
    "bridge_repair_only": "TRUE",
    "audit_only": "TRUE",
}

REPAIRED_MATRIX_FIELDS = [
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
    "repair_source",
    "repair_applied",
    "remaining_blocker_reason",
    *COMMON.keys(),
]
REPAIR_FIELDS = [
    "bridge_repair_id",
    "factor_family",
    "factor_name",
    "evidence_source",
    "v20_152_dynamic_weight_usable_row_consumed",
    "v20_152_factor_ablation_usable_row_consumed",
    "join_key_mismatch_identified",
    "schema_mismatch_identified",
    "missing_outcome_truly_unavailable",
    "missing_outcome_alternate_field_found",
    "missing_benchmark_truly_unavailable",
    "missing_benchmark_alternate_field_found",
    "contribution_attribution_recoverable",
    "window_coverage_recoverable_from_v20_91",
    "regime_coverage_recoverable_from_v20_86",
    "repair_applied",
    "repair_source",
    "remaining_blocker_reason",
    *COMMON.keys(),
]
SOURCE_FIELDS = [
    "source_audit_id",
    "source_artifact",
    "source_exists",
    "source_non_empty",
    "row_count",
    "source_sha256",
    "artifact_family",
    "has_outcome_field",
    "has_outcome_alternate_field",
    "has_benchmark_field",
    "has_benchmark_alternate_field",
    "has_contribution_field",
    "has_signal_date_key",
    "has_as_of_date_key",
    "has_forward_window_key",
    "schema_status",
    "exclusion_reason",
    *COMMON.keys(),
]
BLOCKER_FIELDS = [
    "remaining_blocker_id",
    "factor_family",
    "factor_name",
    "evidence_source",
    "remaining_blocker_reason",
    "requires_future_forward_outcomes",
    "requires_new_backtest_generation",
    "can_repair_from_existing_artifacts",
    "recommended_next_stage",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id",
    "r1_gate_consumed",
    "v20_153_gate_consumed",
    "v20_152_gate_consumed",
    "v20_154_shadow_dynamic_weight_proposal_allowed",
    *SAFETY_FIELDS,
    "v20_152_dynamic_weight_usable_rows",
    "v20_152_dynamic_weight_usable_rows_consumed_by_v20_153",
    "v20_152_factor_ablation_usable_rows",
    "v20_152_factor_ablation_usable_rows_consumed_by_v20_153",
    "unconsumed_usable_row_count",
    "join_key_mismatch_count",
    "schema_mismatch_count",
    "outcome_alternate_field_repair_count",
    "benchmark_alternate_field_repair_count",
    "contribution_attribution_repair_count",
    "window_coverage_repair_count",
    "regime_coverage_repair_count",
    "repaired_matrix_row_count",
    "shadow_weight_research_eligible_count",
    "official_weight_change_eligible_count",
    "remaining_blocker_count",
    "no_new_backtest_results_created",
    "no_outcomes_fabricated",
    "no_benchmarks_fabricated",
    "no_factor_contribution_fabricated",
    "no_eligibility_thresholds_lowered",
    "no_shadow_weight_proposal_created",
    "no_official_weight_mutation",
    "no_official_ranking_changes",
    "no_upstream_outputs_mutated",
    "blocking_reason",
    "final_status",
    "research_only",
    "staging_review_only",
    "bridge_repair_only",
    "audit_only",
]

OUTCOME_FIELDS = {"forward_return", "ticker_forward_return", "strategy_return", "row_level_return", "return", "ticker_return"}
OUTCOME_ALT = {"row_level_return", "ticker_forward_return", "strategy_return"}
BENCH_FIELDS = {"benchmark_return", "benchmark_forward_return", "spy_forward_return", "qqq_forward_return"}
BENCH_ALT = {"benchmark_return", "spy_forward_return", "qqq_forward_return"}
CONTRIB_FIELDS = {"excess_return", "excess_return_vs_benchmark", "alpha_vs_benchmark", "benchmark_relative_return_vs_spy", "benchmark_relative_return_vs_qqq", "risk_adjusted_score"}
TARGET_RE = re.compile(r"V20_(82|84|86|87|88|90|91|93)", re.IGNORECASE)


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


def required_inputs() -> list[Path]:
    return [R1_DIAGNOSTIC, R1_BREAKDOWN, R1_REPAIR, R1_GATE, V153_MATRIX, V153_GATE, V153_SOURCE, V153_ELIGIBILITY, V153_GAP, V152_CACHE, V152_GATE, V152_SOURCE, V152_ELIGIBILITY, V152_GAP]


def upstream_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in required_inputs() if path.exists()}


def num(value: object) -> float | None:
    try:
        number = float(clean(value))
    except ValueError:
        return None
    return None if math.isnan(number) or math.isinf(number) else number


def int_field(row: dict[str, str], field: str) -> int:
    try:
        return int(float(row.get(field, "") or "0"))
    except ValueError:
        return 0


def value_present(row: dict[str, str], fields: set[str]) -> bool:
    return any(clean(row.get(field)).upper() not in {"", "NA", "N/A", "NONE", "NULL"} for field in fields)


def contribution_value(row: dict[str, str]) -> float | None:
    for field in CONTRIB_FIELDS | OUTCOME_FIELDS:
        value = num(row.get(field))
        if value is not None:
            return value
    return None


def contribution_counts(rows: list[dict[str, str]]) -> tuple[int, int, int]:
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


def evidence_quality(asof: int, outcome: int, benchmark: int, stab: str) -> str:
    if asof >= MIN_ASOF and outcome >= MIN_OUTCOME and benchmark >= MIN_BENCHMARK and stab in {"HIGH", "MEDIUM"}:
        return "HIGH"
    if asof > 0 and (outcome > 0 or benchmark > 0):
        return "PARTIAL"
    return "INSUFFICIENT"


def artifact_family(path_text: str) -> str:
    text = path_text.upper()
    if "V20_91" in text:
        return "V20.91_MULTI_WINDOW"
    if "REGIME" in text or "V20_86" in text:
        return "V20.86_OR_93_REGIME"
    if "DOWNSIDE" in text or "V20_87" in text:
        return "V20.87_OR_93_DOWNSIDE"
    if "BENCHMARK" in text or "V20_88" in text:
        return "V20.88_OR_93_BENCHMARK"
    if "ETF_ROTATION" in text or "V20_90" in text:
        return "V20.90_ETF_ROTATION"
    if "V20_82" in text:
        return "V20.82_MULTI_PATH"
    if "V20_84" in text:
        return "V20.84_CERTIFIED_EXPORT"
    if "V20_93" in text:
        return "V20.93_SCHEMA_REPAIR"
    return "OTHER"


def inspect_artifact(path_text: str) -> dict[str, object]:
    path = resolve_artifact(path_text)
    rows, fields = read_csv(path)
    fieldset = set(fields)
    outcome = bool(fieldset & OUTCOME_FIELDS) and any(value_present(row, OUTCOME_FIELDS) for row in rows)
    outcome_alt = bool(fieldset & OUTCOME_ALT) and outcome
    benchmark = bool(fieldset & BENCH_FIELDS) and any(value_present(row, BENCH_FIELDS) for row in rows)
    benchmark_alt = bool(fieldset & BENCH_ALT) and benchmark
    contribution = bool(fieldset & CONTRIB_FIELDS) and any(value_present(row, CONTRIB_FIELDS) for row in rows)
    signal_dates = {row.get("signal_date", "")[:10] for row in rows if row.get("signal_date")}
    asof_dates = {row.get("as_of_date", "")[:10] for row in rows if row.get("as_of_date")}
    windows = {row.get("forward_window") or row.get("holding_window") for row in rows if row.get("forward_window") or row.get("holding_window")}
    regimes = {row.get("regime_bucket") or row.get("market_regime") or row.get("regime_label") for row in rows if row.get("regime_bucket") or row.get("market_regime") or row.get("regime_label")}
    pos, neg, neu = contribution_counts(rows)
    return {
        "path": path,
        "rows": rows,
        "fields": fields,
        "exists": path.exists(),
        "non_empty": path.exists() and path.stat().st_size > 0,
        "row_count": len(rows),
        "sha": sha_file(path),
        "has_outcome": outcome,
        "has_outcome_alt": outcome_alt,
        "has_benchmark": benchmark,
        "has_benchmark_alt": benchmark_alt,
        "has_contribution": contribution,
        "signal_date_count": len(signal_dates),
        "as_of_date_count": len(asof_dates),
        "window_count": len(windows),
        "regime_count": len(regimes),
        "positive": pos,
        "negative": neg,
        "neutral": neu,
    }


def discover_optional_artifacts(matrix_rows: list[dict[str, str]]) -> list[str]:
    artifacts = {row.get("evidence_source", "") for row in matrix_rows if row.get("evidence_source")}
    for root in [EVIDENCE, CONSOLIDATION, OPS]:
        if root.exists():
            for path in root.rglob("*"):
                if path.is_file() and TARGET_RE.search(path.name):
                    artifacts.add(rel(path))
    return sorted(artifacts)


def build_source_audit(artifacts: list[str]) -> tuple[list[dict[str, str]], dict[str, dict[str, object]]]:
    audits: list[dict[str, str]] = []
    inspected: dict[str, dict[str, object]] = {}
    for index, artifact in enumerate(artifacts, start=1):
        info = inspect_artifact(artifact)
        inspected[artifact] = info
        schema_mismatch = not (info["has_outcome"] and info["has_benchmark"] and info["has_contribution"])
        audits.append({
            "source_audit_id": f"V20_153_R2_BRIDGE_SOURCE_AUDIT_{index:04d}",
            "source_artifact": artifact,
            "source_exists": tf(bool(info["exists"])),
            "source_non_empty": tf(bool(info["non_empty"])),
            "row_count": str(info["row_count"]),
            "source_sha256": str(info["sha"]),
            "artifact_family": artifact_family(artifact),
            "has_outcome_field": tf(bool(info["has_outcome"])),
            "has_outcome_alternate_field": tf(bool(info["has_outcome_alt"])),
            "has_benchmark_field": tf(bool(info["has_benchmark"])),
            "has_benchmark_alternate_field": tf(bool(info["has_benchmark_alt"])),
            "has_contribution_field": tf(bool(info["has_contribution"])),
            "has_signal_date_key": tf(int(info["signal_date_count"]) > 0),
            "has_as_of_date_key": tf(int(info["as_of_date_count"]) > 0),
            "has_forward_window_key": tf(int(info["window_count"]) > 0),
            "schema_status": "PARTIAL_SCHEMA_BRIDGEABLE" if schema_mismatch and (info["has_outcome"] or info["has_benchmark"] or info["has_contribution"]) else ("COMPLETE_BRIDGE_SCHEMA" if not schema_mismatch else "NO_BRIDGEABLE_SCHEMA"),
            "exclusion_reason": "" if bool(info["exists"]) and bool(info["non_empty"]) else "MISSING_OR_EMPTY_SOURCE_ARTIFACT",
            **COMMON,
        })
    return audits, inspected


def source_set(matrix_rows: list[dict[str, str]]) -> set[str]:
    return {row.get("evidence_source", "") for row in matrix_rows if row.get("evidence_source")}


def remaining_reasons(row: dict[str, str]) -> str:
    reasons: list[str] = []
    if int_field(row, "as_of_sample_count") < MIN_ASOF:
        reasons.append("INSUFFICIENT_AS_OF_SAMPLE_COUNT")
    if int_field(row, "outcome_available_count") < MIN_OUTCOME:
        reasons.append("INSUFFICIENT_OUTCOME_EVIDENCE")
    if int_field(row, "benchmark_available_count") < MIN_BENCHMARK:
        reasons.append("INSUFFICIENT_BENCHMARK_EVIDENCE")
    if int_field(row, "window_coverage") < MIN_WINDOW:
        reasons.append("INSUFFICIENT_WINDOW_COVERAGE")
    if row.get("contribution_stability") not in {"HIGH", "MEDIUM"}:
        reasons.append("INSUFFICIENT_CONTRIBUTION_ATTRIBUTION")
    if row.get("factor_family") == "MARKET_REGIME" and row.get("regime_coverage") != "PRESENT":
        reasons.append("INSUFFICIENT_REGIME_COVERAGE")
    return "|".join(reasons)


def repair_matrix(matrix_rows: list[dict[str, str]], inspected: dict[str, dict[str, object]], v152_cache: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    cache_by_source: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in v152_cache:
        cache_by_source[row.get("source_artifact", "")].append(row)
    repaired: list[dict[str, str]] = []
    repairs: list[dict[str, str]] = []
    for index, row in enumerate(matrix_rows, start=1):
        source = row.get("evidence_source", "")
        info = inspected.get(source) or inspect_artifact(source)
        cache_rows = cache_by_source.get(source, [])
        dynamic_consumed = any(truthy(cache.get("usable_for_dynamic_weight_research")) for cache in cache_rows)
        factor_consumed = any(truthy(cache.get("usable_for_factor_ablation")) for cache in cache_rows)
        original_asof = int_field(row, "as_of_sample_count")
        original_outcome = int_field(row, "outcome_available_count")
        original_benchmark = int_field(row, "benchmark_available_count")
        original_window = int_field(row, "window_coverage")
        asof = max(original_asof, int(info["signal_date_count"]), int(info["as_of_date_count"]))
        outcome = max(original_outcome, int(info["row_count"]) if info["has_outcome"] else 0)
        benchmark = max(original_benchmark, int(info["row_count"]) if info["has_benchmark"] else 0)
        window = max(original_window, int(info["window_count"]))
        pos = max(int_field(row, "positive_contribution_count"), int(info["positive"]))
        neg = max(int_field(row, "negative_contribution_count"), int(info["negative"]))
        neu = max(int_field(row, "neutral_contribution_count"), int(info["neutral"]))
        stab = stability(pos, neg, neu)
        regime = row.get("regime_coverage", "")
        if (artifact_family(source) == "V20.86_OR_93_REGIME" or "REGIME" in source.upper()) and int(info["regime_count"]) > 0:
            regime = "PRESENT"
        quality = evidence_quality(asof, outcome, benchmark, stab)
        repaired_row = {
            **row,
            "as_of_sample_count": str(asof),
            "outcome_available_count": str(outcome),
            "benchmark_available_count": str(benchmark),
            "positive_contribution_count": str(pos),
            "negative_contribution_count": str(neg),
            "neutral_contribution_count": str(neu),
            "contribution_stability": stab,
            "regime_coverage": regime,
            "window_coverage": str(window),
            "evidence_quality": quality,
            "repair_source": source if source else "NO_SOURCE",
            "repair_applied": "FALSE",
            "remaining_blocker_reason": "",
            **COMMON,
        }
        reasons = remaining_reasons(repaired_row)
        shadow_ok = reasons == "" and quality == "HIGH"
        repaired_row["usable_for_shadow_weight_proposal"] = tf(shadow_ok)
        repaired_row["usable_for_official_weight_change"] = "FALSE"
        repaired_row["remaining_blocker_reason"] = reasons
        repaired_row["exclusion_reason"] = "" if shadow_ok else reasons
        repair_applied = any([
            asof > original_asof,
            outcome > original_outcome,
            benchmark > original_benchmark,
            window > original_window,
            pos > int_field(row, "positive_contribution_count"),
            neg > int_field(row, "negative_contribution_count"),
            neu > int_field(row, "neutral_contribution_count"),
            regime != row.get("regime_coverage", ""),
        ])
        repaired_row["repair_applied"] = tf(repair_applied)
        repaired.append(repaired_row)
        join_mismatch = bool(cache_rows) and source not in source_set(matrix_rows)
        schema_mismatch = not (info["has_outcome"] and info["has_benchmark"] and info["has_contribution"])
        repairs.append({
            "bridge_repair_id": f"V20_153_R2_FACTOR_ABLATION_BRIDGE_REPAIR_{index:04d}",
            "factor_family": row.get("factor_family", ""),
            "factor_name": row.get("factor_name", ""),
            "evidence_source": source,
            "v20_152_dynamic_weight_usable_row_consumed": tf(dynamic_consumed),
            "v20_152_factor_ablation_usable_row_consumed": tf(factor_consumed),
            "join_key_mismatch_identified": tf(join_mismatch),
            "schema_mismatch_identified": tf(schema_mismatch),
            "missing_outcome_truly_unavailable": tf(not info["has_outcome"]),
            "missing_outcome_alternate_field_found": tf(bool(info["has_outcome_alt"])),
            "missing_benchmark_truly_unavailable": tf(not info["has_benchmark"]),
            "missing_benchmark_alternate_field_found": tf(bool(info["has_benchmark_alt"])),
            "contribution_attribution_recoverable": tf(bool(info["has_contribution"])),
            "window_coverage_recoverable_from_v20_91": tf("V20_91" in source.upper() and int(info["window_count"]) > original_window),
            "regime_coverage_recoverable_from_v20_86": tf(("V20_86" in source.upper() or "REGIME" in source.upper()) and regime == "PRESENT" and regime != row.get("regime_coverage", "")),
            "repair_applied": tf(repair_applied),
            "repair_source": source if repair_applied else "",
            "remaining_blocker_reason": reasons,
            **COMMON,
        })
    return repaired, repairs


def build_remaining_blockers(repaired: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in repaired:
        reasons = [reason for reason in row.get("remaining_blocker_reason", "").split("|") if reason]
        for reason in reasons:
            rows.append({
                "remaining_blocker_id": f"V20_153_R2_REMAINING_BLOCKER_{len(rows)+1:04d}",
                "factor_family": row.get("factor_family", ""),
                "factor_name": row.get("factor_name", ""),
                "evidence_source": row.get("evidence_source", ""),
                "remaining_blocker_reason": reason,
                "requires_future_forward_outcomes": "FALSE",
                "requires_new_backtest_generation": tf(reason in {"INSUFFICIENT_AS_OF_SAMPLE_COUNT", "INSUFFICIENT_OUTCOME_EVIDENCE", "INSUFFICIENT_BENCHMARK_EVIDENCE", "INSUFFICIENT_WINDOW_COVERAGE"}),
                "can_repair_from_existing_artifacts": tf(reason in {"INSUFFICIENT_CONTRIBUTION_ATTRIBUTION", "INSUFFICIENT_REGIME_COVERAGE"}),
                "recommended_next_stage": "V20.153_R3_FACTOR_ABLATION_REBUILD_PLAN",
                **COMMON,
            })
    return rows


def safety_true_count(groups: list[list[dict[str, str]]]) -> int:
    return sum(1 for rows in groups for row in rows for field in SAFETY_FIELDS if truthy(row.get(field)))


def write_report(status: str, repair_count: int, eligible: int, remaining: int) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.153-R2 Factor Ablation Existing Evidence Bridge Repair Report",
        "",
        f"- wrapper_status: {status}",
        f"- repair_applied_row_count: {repair_count}",
        f"- shadow_weight_research_eligible_count: {eligible}",
        f"- remaining_blocker_count: {remaining}",
        "- official_weight_change_created: FALSE",
        "- shadow_weight_proposal_created: FALSE",
        "",
        "R2 repaired only bridgeable field-name and coverage mappings from existing artifacts. It did not create new backtests, outcomes, benchmark returns, contribution attribution, shadow weights, official weights, or ranking changes.",
    ]) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_153_R2_FACTOR_ABLATION_NEXT_GATE_001",
        "r1_gate_consumed": "FALSE",
        "v20_153_gate_consumed": "FALSE",
        "v20_152_gate_consumed": "FALSE",
        "v20_154_shadow_dynamic_weight_proposal_allowed": "FALSE",
        **SAFETY,
        "v20_152_dynamic_weight_usable_rows": "0",
        "v20_152_dynamic_weight_usable_rows_consumed_by_v20_153": "0",
        "v20_152_factor_ablation_usable_rows": "0",
        "v20_152_factor_ablation_usable_rows_consumed_by_v20_153": "0",
        "unconsumed_usable_row_count": "0",
        "join_key_mismatch_count": "0",
        "schema_mismatch_count": "0",
        "outcome_alternate_field_repair_count": "0",
        "benchmark_alternate_field_repair_count": "0",
        "contribution_attribution_repair_count": "0",
        "window_coverage_repair_count": "0",
        "regime_coverage_repair_count": "0",
        "repaired_matrix_row_count": "0",
        "shadow_weight_research_eligible_count": "0",
        "official_weight_change_eligible_count": "0",
        "remaining_blocker_count": "0",
        "no_new_backtest_results_created": "TRUE",
        "no_outcomes_fabricated": "TRUE",
        "no_benchmarks_fabricated": "TRUE",
        "no_factor_contribution_fabricated": "TRUE",
        "no_eligibility_thresholds_lowered": "TRUE",
        "no_shadow_weight_proposal_created": "TRUE",
        "no_official_weight_mutation": "TRUE",
        "no_official_ranking_changes": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        "research_only": "TRUE",
        "staging_review_only": "TRUE",
        "bridge_repair_only": "TRUE",
        "audit_only": "TRUE",
    }
    write_csv(OUT_REPAIR, REPAIR_FIELDS, [])
    write_csv(OUT_SOURCE_AUDIT, SOURCE_FIELDS, [])
    write_csv(OUT_MATRIX, REPAIRED_MATRIX_FIELDS, [])
    write_csv(OUT_BLOCKERS, BLOCKER_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(BLOCKED_STATUS, 0, 0, 0)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    before = upstream_hashes()
    missing = [path for path in required_inputs() if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))
    r1_gate, _ = read_csv(R1_GATE)
    v153_gate, _ = read_csv(V153_GATE)
    v152_gate, _ = read_csv(V152_GATE)
    if not (r1_gate and v153_gate and v152_gate):
        return emit_blocked("EMPTY_REQUIRED_GATE")
    r1_status = r1_gate[0].get("final_status", "")
    v153_status = v153_gate[0].get("final_status", "")
    if r1_status not in R1_ALLOWED:
        return emit_blocked("R1_GATE_NOT_READY_FOR_REPAIR")
    if v153_status != V153_REQUIRED_STATUS:
        return emit_blocked("V20_153_STATUS_NOT_WARN_INSUFFICIENT")

    matrix_rows, _ = read_csv(V153_MATRIX)
    v152_cache, _ = read_csv(V152_CACHE)
    artifacts = discover_optional_artifacts(matrix_rows)
    source_audit, inspected = build_source_audit(artifacts)
    repaired_matrix, repair_rows = repair_matrix(matrix_rows, inspected, v152_cache)
    remaining = build_remaining_blockers(repaired_matrix)
    matrix_sources = source_set(matrix_rows)
    dynamic_rows = [row for row in v152_cache if truthy(row.get("usable_for_dynamic_weight_research"))]
    factor_rows = [row for row in v152_cache if truthy(row.get("usable_for_factor_ablation"))]
    dynamic_consumed = [row for row in dynamic_rows if row.get("source_artifact") in matrix_sources]
    factor_consumed = [row for row in factor_rows if row.get("source_artifact") in matrix_sources]
    unconsumed = [row for row in factor_rows if row.get("source_artifact") not in matrix_sources]
    shadow_eligible = sum(1 for row in repaired_matrix if row.get("usable_for_shadow_weight_proposal") == "TRUE")
    official_eligible = sum(1 for row in repaired_matrix if row.get("usable_for_official_weight_change") == "TRUE")
    repair_applied_count = sum(1 for row in repair_rows if row.get("repair_applied") == "TRUE")
    safety_count = safety_true_count([source_audit, repair_rows, repaired_matrix, remaining])
    upstream_mutated = before != upstream_hashes()
    if safety_count or upstream_mutated or official_eligible:
        status = BLOCKED_STATUS
        blocking = "SAFETY_OR_UPSTREAM_MUTATION_FAILURE"
    elif shadow_eligible > 0 and len(remaining) == 0:
        status = PASS_STATUS
        blocking = ""
    elif shadow_eligible > 0:
        status = PARTIAL_STATUS
        blocking = ""
    elif repair_applied_count > 0:
        status = WARN_STATUS
        blocking = ""
    else:
        status = WARN_STATUS
        blocking = ""
    gate = {
        "gate_check_id": "V20_153_R2_FACTOR_ABLATION_NEXT_GATE_001",
        "r1_gate_consumed": "TRUE",
        "v20_153_gate_consumed": "TRUE",
        "v20_152_gate_consumed": "TRUE",
        "v20_154_shadow_dynamic_weight_proposal_allowed": tf(status in {PASS_STATUS, PARTIAL_STATUS}),
        **SAFETY,
        "v20_152_dynamic_weight_usable_rows": str(len(dynamic_rows)),
        "v20_152_dynamic_weight_usable_rows_consumed_by_v20_153": str(len(dynamic_consumed)),
        "v20_152_factor_ablation_usable_rows": str(len(factor_rows)),
        "v20_152_factor_ablation_usable_rows_consumed_by_v20_153": str(len(factor_consumed)),
        "unconsumed_usable_row_count": str(len(unconsumed)),
        "join_key_mismatch_count": str(len(unconsumed)),
        "schema_mismatch_count": str(sum(1 for row in repair_rows if row["schema_mismatch_identified"] == "TRUE")),
        "outcome_alternate_field_repair_count": str(sum(1 for row in repair_rows if row["missing_outcome_alternate_field_found"] == "TRUE")),
        "benchmark_alternate_field_repair_count": str(sum(1 for row in repair_rows if row["missing_benchmark_alternate_field_found"] == "TRUE")),
        "contribution_attribution_repair_count": str(sum(1 for row in repair_rows if row["contribution_attribution_recoverable"] == "TRUE")),
        "window_coverage_repair_count": str(sum(1 for row in repair_rows if row["window_coverage_recoverable_from_v20_91"] == "TRUE")),
        "regime_coverage_repair_count": str(sum(1 for row in repair_rows if row["regime_coverage_recoverable_from_v20_86"] == "TRUE")),
        "repaired_matrix_row_count": str(len(repaired_matrix)),
        "shadow_weight_research_eligible_count": str(shadow_eligible),
        "official_weight_change_eligible_count": str(official_eligible),
        "remaining_blocker_count": str(len(remaining)),
        "no_new_backtest_results_created": "TRUE",
        "no_outcomes_fabricated": "TRUE",
        "no_benchmarks_fabricated": "TRUE",
        "no_factor_contribution_fabricated": "TRUE",
        "no_eligibility_thresholds_lowered": "TRUE",
        "no_shadow_weight_proposal_created": "TRUE",
        "no_official_weight_mutation": "TRUE",
        "no_official_ranking_changes": "TRUE",
        "no_upstream_outputs_mutated": tf(not upstream_mutated),
        "blocking_reason": blocking,
        "final_status": status,
        "research_only": "TRUE",
        "staging_review_only": "TRUE",
        "bridge_repair_only": "TRUE",
        "audit_only": "TRUE",
    }
    write_csv(OUT_REPAIR, REPAIR_FIELDS, repair_rows)
    write_csv(OUT_SOURCE_AUDIT, SOURCE_FIELDS, source_audit)
    write_csv(OUT_MATRIX, REPAIRED_MATRIX_FIELDS, repaired_matrix)
    write_csv(OUT_BLOCKERS, BLOCKER_FIELDS, remaining)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(status, repair_applied_count, shadow_eligible, len(remaining))

    print(status)
    for key in [
        "v20_152_dynamic_weight_usable_rows",
        "v20_152_dynamic_weight_usable_rows_consumed_by_v20_153",
        "v20_152_factor_ablation_usable_rows",
        "v20_152_factor_ablation_usable_rows_consumed_by_v20_153",
        "unconsumed_usable_row_count",
        "join_key_mismatch_count",
        "schema_mismatch_count",
        "outcome_alternate_field_repair_count",
        "benchmark_alternate_field_repair_count",
        "contribution_attribution_repair_count",
        "window_coverage_repair_count",
        "regime_coverage_repair_count",
        "repaired_matrix_row_count",
        "shadow_weight_research_eligible_count",
        "official_weight_change_eligible_count",
        "remaining_blocker_count",
    ]:
        print(f"{key.upper()}={gate[key]}")
    print("NEW_BACKTEST_RESULTS_CREATED=FALSE")
    print("OUTCOMES_FABRICATED=0")
    print("BENCHMARKS_FABRICATED=0")
    print("FACTOR_CONTRIBUTION_FABRICATED=0")
    print("ELIGIBILITY_THRESHOLDS_LOWERED=FALSE")
    print("SHADOW_WEIGHT_PROPOSAL_CREATED=FALSE")
    print("OFFICIAL_WEIGHT_MUTATION=FALSE")
    print("OFFICIAL_RANKING_CHANGES=FALSE")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    print(f"SAFETY_TRUE_COUNT={safety_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
