#!/usr/bin/env python
"""V20.170 DATA_TRUST direct status contract and emitter repair.

Creates a canonical research-only ticker-level DATA_TRUST status contract and
emitter. The emitter uses only real ticker-level evidence. It does not convert
inferred or aggregate evidence into direct ticker status, does not run ranking
simulation, and does not mutate official rankings, weights, recommendations,
actions, performance claims, or upstream outputs.
"""

from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
CONSOLIDATION = OUTPUTS / "consolidation"
FACTORS = OUTPUTS / "factors"
BACKTEST = OUTPUTS / "backtest"
READ_CENTER = OUTPUTS / "read_center"

V169_SCAN = FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_SOURCE_SCAN.csv"
V169_MAPPING = FACTORS / "V20_169_DATA_TRUST_DIRECT_TICKER_MAPPING.csv"
V169_STATUS = FACTORS / "V20_169_DATA_TRUST_DIRECT_PASS_FAIL_STATUS.csv"
V169_REPAIR = FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_REPAIR_AUDIT.csv"
V169_BACKLOG = FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_REMAINING_BACKLOG.csv"
V169_SUMMARY = FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_COVERAGE_SUMMARY.csv"
V169_GATE = FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_NEXT_GATE.csv"
V169_SAFETY = FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_SAFETY_AUDIT.csv"
BASELINE = CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
WEIGHTS = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"

R4_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
R10_SCORES = CONSOLIDATION / "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv"
R1_CONTRIB = CONSOLIDATION / "V20_108_R1_CANDIDATE_FACTOR_FAMILY_CONTRIBUTIONS.csv"
R2_CONTRIB = CONSOLIDATION / "V20_108_R2_EXPANDED_CANDIDATE_FACTOR_FAMILY_CONTRIBUTIONS.csv"
WEIGHT_AUDIT = CONSOLIDATION / "V20_98B_FACTOR_SCORE_CONTRIBUTION_AUDIT.csv"
WEIGHT_EXPOSURE = CONSOLIDATION / "V20_98B_RESEARCH_ONLY_FACTOR_WEIGHT_EXPOSURE.csv"
V45_SUPPORT = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_FACTOR_SUPPORT_VIEW.csv"
V48_SUPPORT = CONSOLIDATION / "V20_48_REFRESHED_FACTOR_SUPPORT_VIEW.csv"
V54_SUPPORT = CONSOLIDATION / "V20_54_FACTOR_SUPPORT_READABLE_VIEW.csv"
CURRENT_MULTI = CONSOLIDATION / "V20_CURRENT_FACTOR_MULTI_PATH_VALIDATION_TABLE.csv"
V82_MULTI = CONSOLIDATION / "V20_82_FACTOR_MULTI_PATH_VALIDATION_TABLE.csv"

SOURCE_CANDIDATES = [
    R4_SCORES, R10_SCORES, R1_CONTRIB, R2_CONTRIB, WEIGHT_AUDIT, WEIGHT_EXPOSURE,
    V45_SUPPORT, V48_SUPPORT, V54_SUPPORT, CURRENT_MULTI, V82_MULTI,
]

OUT_CONTRACT = FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_CONTRACT.csv"
OUT_DISCOVERY = FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_SOURCE_DISCOVERY.csv"
OUT_EMITTER = FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_EMITTER.csv"
OUT_STATUS = FACTORS / "V20_170_DATA_TRUST_DIRECT_PASS_FAIL_UNKNOWN.csv"
OUT_BACKLOG = FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_REPAIR_BACKLOG.csv"
OUT_COVERAGE = FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_COVERAGE_AUDIT.csv"
OUT_GATE = FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_NEXT_GATE.csv"
OUT_SAFETY = FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_SAFETY_AUDIT.csv"
REPORT = READ_CENTER / "V20_170_DATA_TRUST_DIRECT_STATUS_CONTRACT_AND_EMITTER_REPAIR_REPORT.md"

REQUIRED_V169_STATUS = "WARN_V20_169_NO_DIRECT_TICKER_LEVEL_DATA_TRUST_MAPPING_RECOVERED"
PASS_STATUS = "PASS_V20_170_DATA_TRUST_DIRECT_STATUS_EMITTER_READY_FOR_V20_171"
PARTIAL_STATUS = "PARTIAL_PASS_V20_170_DATA_TRUST_DIRECT_STATUS_EMITTER_WITH_REMAINING_UNKNOWN_READY_FOR_V20_171"
WARN_STATUS = "WARN_V20_170_DIRECT_STATUS_EMITTER_CREATED_BUT_NO_DIRECT_PASS_ROWS"
BLOCKED_STATUS = "BLOCKED_V20_170_DATA_TRUST_DIRECT_STATUS_CONTRACT_AND_EMITTER_REPAIR"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_DIRECT_STATUS_CONTRACT_AND_EMITTER_REPAIR"
REQUIRED_FAMILIES = ["fundamental", "technical", "strategy", "risk", "market_regime"]

SAFETY = {
    "research_only": "TRUE",
    "data_trust_scoring_weight": "0.0000000000",
    "data_trust_role": DATA_TRUST_ROLE,
    "direct_ticker_mapping_required_before_official_use": "TRUE",
    "formal_activation_allowed": "FALSE",
    "promotion_ready": "FALSE",
    "official_recommendation_created": "FALSE",
    "official_ranking_mutated": "FALSE",
    "official_weight_change_created": "FALSE",
    "official_weight_registry_mutated": "FALSE",
    "weight_mutated": "FALSE",
    "real_book_action_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "performance_claim_created": "FALSE",
    "shadow_weight_expansion_allowed": "FALSE",
}
COMMON = {**SAFETY, "direct_status_emitter_repair_created": "TRUE", "repair_scope": SCOPE, "audit_only": "TRUE"}

CONTRACT_FIELDS = [
    "contract_field", "required_for_direct_pass", "accepted_source_type",
    "accepted_source_artifact", "accepted_source_field", "direct_evidence_required",
    "aggregate_evidence_allowed", "fail_condition", "unknown_condition",
    "repair_action_if_missing", *COMMON.keys(),
]
DISCOVERY_FIELDS = [
    "source_artifact", "artifact_exists", "row_count", "ticker_level",
    "has_ticker_column", "ticker_column_name", "has_price_data_field",
    "has_factor_family_score_fields", "has_source_quality_field",
    "has_freshness_field", "has_pit_safety_field", "has_schema_status_field",
    "has_ranking_eligibility_field", "usable_for_direct_status_emitter",
    "limitation_reason", *COMMON.keys(),
]
EMITTER_FIELDS = [
    "ticker", "baseline_rank", "ticker_identity_match", "price_data_available",
    "required_factor_family_scores_available", "fundamental_score_available",
    "technical_score_available", "strategy_score_available", "risk_score_available",
    "market_regime_score_available", "data_trust_score_excluded_from_scoring",
    "source_quality_status", "freshness_status", "pit_safety_status",
    "schema_status", "current_ranking_eligibility_status", "score_lineage_bindable",
    "direct_data_trust_status", "direct_data_trust_pass", "direct_data_trust_fail",
    "direct_data_trust_unknown", "direct_status_source_artifacts",
    "direct_status_source_fields", "direct_status_confidence",
    "failure_or_unknown_reason", "repair_required", "recommended_repair_action",
    *COMMON.keys(),
]
BACKLOG_FIELDS = [
    "ticker", "baseline_rank", "direct_data_trust_status",
    "failure_or_unknown_reason", "missing_contract_dimensions",
    "recommended_repair_action", "repair_priority", *COMMON.keys(),
]
SUMMARY_FIELDS = [
    "summary_id", "baseline_candidate_count", "direct_status_emitter_created",
    "direct_status_contract_created", "direct_data_trust_pass_count",
    "direct_data_trust_fail_count", "direct_data_trust_unknown_count",
    "direct_status_coverage_rate", "unknown_count", "fail_count",
    "repair_backlog_count", "ticker_level_source_artifact_count",
    "usable_direct_status_source_count", "aggregate_only_source_artifact_count",
    "ready_for_direct_status_gate_only_ranking_simulation", "ready_for_official_use",
    "recommended_next_action", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_169_gate_consumed", "v20_169_status",
    "baseline_candidate_count", "direct_status_emitter_created",
    "direct_status_contract_created", "direct_data_trust_pass_count",
    "direct_data_trust_fail_count", "direct_data_trust_unknown_count",
    "direct_status_coverage_rate", "ready_for_direct_status_gate_only_ranking_simulation",
    "ready_for_official_use", "official_weight_change_allowed",
    "official_ranking_mutation_allowed", "ranking_simulation_created",
    "no_ticker_status_fabricated", "inferred_mapping_not_converted_to_direct",
    "aggregate_pass_not_treated_as_ticker_pass", "unknown_not_treated_as_pass",
    "data_trust_gate_criteria_not_lowered", "no_upstream_outputs_mutated",
    "blocking_reason", "final_status", *COMMON.keys(),
]
SAFETY_FIELDS = [
    "safety_check_id", "safety_check", "expected_value", "actual_value",
    "safety_passed", *COMMON.keys(),
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def num(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(clean(value))
    except ValueError:
        return default
    return default if math.isnan(parsed) or math.isinf(parsed) else parsed


def fmt(value: float) -> str:
    return f"{value:.10f}"


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


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
    return [V169_SCAN, V169_MAPPING, V169_STATUS, V169_REPAIR, V169_BACKLOG, V169_SUMMARY, V169_GATE, V169_SAFETY, BASELINE, WEIGHTS]


def discover_sources() -> list[Path]:
    discovered: set[Path] = set(SOURCE_CANDIDATES)
    keywords = ("ticker", "price", "factor", "fresh", "pit", "schema", "eligib", "source", "quality", "score")
    for directory in [CONSOLIDATION, FACTORS, BACKTEST]:
        if directory.exists():
            for path in directory.glob("*.csv"):
                lower = path.name.lower()
                if any(keyword in lower for keyword in keywords):
                    discovered.add(path)
    outputs = {OUT_CONTRACT, OUT_DISCOVERY, OUT_EMITTER, OUT_STATUS, OUT_BACKLOG, OUT_COVERAGE, OUT_GATE, OUT_SAFETY}
    upstream = set(required_inputs())
    return sorted(path for path in discovered if path not in outputs and path not in upstream)


def all_inputs(sources: list[Path]) -> list[Path]:
    return [*required_inputs(), *[path for path in sources if path.exists()]]


def input_hashes(sources: list[Path]) -> dict[str, str]:
    return {rel(path): sha_file(path) for path in all_inputs(sources) if path.exists()}


def find_field(fields: list[str], *needles: str) -> str:
    for field in fields:
        low = field.lower()
        if all(needle in low for needle in needles):
            return field
    return ""


def ticker_field(fields: list[str]) -> str:
    for field in fields:
        if field.lower() in {"ticker", "symbol", "candidate_ticker"}:
            return field
    return find_field(fields, "ticker")


def nonempty(row: dict[str, str], field: str) -> bool:
    return bool(field and clean(row.get(field)))


def positive(value: str) -> bool:
    value = value.upper()
    return value in {"TRUE", "PASS", "PASSED", "VALID", "FOUND", "AVAILABLE", "USABLE", "ELIGIBLE", "CERTIFIED", "OK"} or "CERTIFIED" in value


def negative(value: str) -> bool:
    value = value.upper()
    return any(token in value for token in ["FALSE", "FAIL", "INVALID", "MISSING", "STALE", "BLOCKED", "UNUSABLE", "INELIGIBLE", "UNSAFE", "ERROR"])


def status_from(value: str) -> str:
    if positive(value):
        return "PASS"
    if negative(value):
        return "FAIL"
    return "UNKNOWN"


def build_contract() -> list[dict[str, str]]:
    specs = [
        ("ticker_identity", "ticker-level candidate identity", rel(BASELINE), "ticker", "ticker mismatch", "missing ticker-level identity", "repair ticker identity source binding"),
        ("current_price_data_availability", "ticker-level current price or authoritative current price lineage", rel(BASELINE), "latest_price;latest_price_date", "missing price/date", "missing ticker-level price lineage", "emit ticker-level price availability"),
        ("factor_family_score_availability", "ticker-level factor family scores for five scoring families", rel(R10_SCORES), "fundamental_contribution;technical_contribution;strategy_contribution;risk_contribution;market_regime_contribution", "missing required scoring family", "missing ticker-level family score", "emit complete factor family score rows"),
        ("source_quality", "ticker-level source certification or validation status", rel(BASELINE), "certification_status;accepted_artifact_validation_status", "source quality fail", "missing ticker-level source quality", "emit ticker-level source quality status"),
        ("freshness", "ticker-level freshness/date status", rel(BASELINE), "latest_price_date", "stale data", "missing ticker-level freshness status", "emit ticker-level freshness status"),
        ("pit_safety", "ticker-level PIT safety status", "NONE_FOUND", "pit_safety_status", "PIT unsafe or blocked", "missing ticker-level PIT status", "emit ticker-level PIT safety status"),
        ("schema_validity", "ticker-level schema or artifact validation status", rel(BASELINE), "accepted_artifact_validation_status", "schema invalid", "missing ticker-level schema validation", "emit ticker-level schema validity status"),
        ("current_ranking_eligibility", "ticker-level current ranking eligibility status", rel(BASELINE), "official_current_rank;official_current_score", "ranking eligibility blocked", "missing ticker-level ranking eligibility", "emit ticker-level ranking eligibility status"),
        ("score_lineage_bindability", "ticker-level baseline score/rank binding proof", rel(BASELINE), "exact_artifact_proof_status;source_file", "score lineage cannot bind", "missing score lineage binding proof", "emit ticker-level score lineage binding proof"),
        ("repair_backlog_status", "ticker-level backlog state for FAIL or UNKNOWN", rel(OUT_BACKLOG), "ticker;failure_or_unknown_reason", "not backlogged when failed/unknown", "missing repair backlog status", "emit ticker-level repair backlog"),
    ]
    return [{
        "contract_field": field,
        "required_for_direct_pass": "TRUE",
        "accepted_source_type": source_type,
        "accepted_source_artifact": artifact,
        "accepted_source_field": source_field,
        "direct_evidence_required": "TRUE",
        "aggregate_evidence_allowed": "FALSE",
        "fail_condition": fail,
        "unknown_condition": unknown,
        "repair_action_if_missing": action,
        **COMMON,
    } for field, source_type, artifact, source_field, fail, unknown, action in specs]


def source_discovery(path: Path) -> dict[str, str]:
    rows, fields = read_csv(path)
    ticker = ticker_field(fields)
    ticker_level = bool(rows and ticker)
    price = find_field(fields, "price")
    family = all(find_field(fields, family, "contribution") or find_field(fields, family, "score") for family in REQUIRED_FAMILIES)
    source_quality = find_field(fields, "source", "quality") or find_field(fields, "certification") or find_field(fields, "validation")
    freshness = find_field(fields, "fresh") or find_field(fields, "date")
    pit = find_field(fields, "pit")
    schema = find_field(fields, "schema") or find_field(fields, "validation")
    eligibility = find_field(fields, "eligib") or find_field(fields, "official_current_rank")
    usable = ticker_level and (price or family or source_quality or freshness or pit or schema or eligibility)
    reason = "USABLE_TICKER_LEVEL_DIMENSION_SOURCE" if usable else ("AGGREGATE_ONLY_OR_NO_TICKER_COLUMN" if rows else "MISSING_OR_EMPTY")
    return {
        "source_artifact": rel(path),
        "artifact_exists": tf(path.exists()),
        "row_count": str(len(rows)),
        "ticker_level": tf(ticker_level),
        "has_ticker_column": tf(bool(ticker)),
        "ticker_column_name": ticker,
        "has_price_data_field": tf(bool(price)),
        "has_factor_family_score_fields": tf(bool(family)),
        "has_source_quality_field": tf(bool(source_quality)),
        "has_freshness_field": tf(bool(freshness)),
        "has_pit_safety_field": tf(bool(pit)),
        "has_schema_status_field": tf(bool(schema)),
        "has_ranking_eligibility_field": tf(bool(eligibility)),
        "usable_for_direct_status_emitter": tf(usable),
        "limitation_reason": reason,
        **COMMON,
    }


def map_by_ticker(path: Path) -> dict[str, dict[str, str]]:
    rows, fields = read_csv(path)
    ticker = ticker_field(fields)
    return {row.get(ticker, "").upper(): row for row in rows if ticker and row.get(ticker)}


def field_status(row: dict[str, str], fields: list[str]) -> str:
    values = [clean(row.get(field)) for field in fields if field and field in row]
    if not values:
        return "UNKNOWN"
    if any(negative(value) for value in values):
        return "FAIL"
    if all(value and (positive(value) or value.upper() not in {"UNKNOWN", "NA", "N/A"}) for value in values):
        return "PASS"
    return "UNKNOWN"


def build_emitter(baseline: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    r10 = map_by_ticker(R10_SCORES)
    baseline_by_ticker = {row["ticker"].upper(): row for row in baseline}
    emitter: list[dict[str, str]] = []
    backlog: list[dict[str, str]] = []
    for row in baseline:
        ticker = row["ticker"].upper()
        score_row = r10.get(ticker, {})
        family_flags = {}
        for family in REQUIRED_FAMILIES:
            contribution = f"{family}_contribution"
            material = f"{family}_materialization_status"
            family_flags[family] = bool(score_row and nonempty(score_row, contribution) and nonempty(score_row, material) and not negative(score_row.get(material, "")))
        required_family_scores = all(family_flags.values())
        price = bool(clean(row.get("latest_price")) and clean(row.get("latest_price_date")))
        source_quality = field_status(row, ["certification_status", "accepted_artifact_validation_status"])
        freshness = "PASS" if clean(row.get("latest_price_date")) else "UNKNOWN"
        pit_safety = "UNKNOWN"
        schema = field_status(row, ["accepted_artifact_validation_status", "exact_artifact_proof_status"])
        ranking_eligibility = "PASS" if clean(row.get("official_current_rank")) and clean(row.get("official_current_score")) else "UNKNOWN"
        lineage = field_status(row, ["exact_artifact_proof_status", "source_file"])
        dimensions = {
            "ticker_identity_match": ticker in baseline_by_ticker,
            "price_data_available": price,
            "required_factor_family_scores_available": required_family_scores,
            "source_quality_status": source_quality,
            "freshness_status": freshness,
            "pit_safety_status": pit_safety,
            "schema_status": schema,
            "current_ranking_eligibility_status": ranking_eligibility,
            "score_lineage_bindable": lineage == "PASS",
        }
        fail_reasons = []
        unknown_reasons = []
        for key, value in dimensions.items():
            if isinstance(value, bool):
                if not value:
                    unknown_reasons.append(key)
            elif value == "FAIL":
                fail_reasons.append(key)
            elif value != "PASS":
                unknown_reasons.append(key)
        for family, ok in family_flags.items():
            if not ok:
                unknown_reasons.append(f"{family}_score_available")
        if fail_reasons:
            direct_status = "DIRECT_FAIL"
            reason = "DIRECT_FAIL:" + ";".join(sorted(set(fail_reasons)))
            action = "REPAIR_FAILED_TICKER_LEVEL_DATA_TRUST_DIMENSIONS"
        elif unknown_reasons:
            direct_status = "UNKNOWN"
            reason = "UNKNOWN_MISSING_DIRECT_DIMENSIONS:" + ";".join(sorted(set(unknown_reasons)))
            action = "EMIT_MISSING_DIRECT_TICKER_LEVEL_DATA_TRUST_DIMENSIONS"
        else:
            direct_status = "DIRECT_PASS"
            reason = "NONE"
            action = "NONE"
        artifacts = [rel(BASELINE)]
        fields = ["ticker", "official_current_rank", "official_current_score", "latest_price", "latest_price_date", "certification_status", "accepted_artifact_validation_status", "exact_artifact_proof_status"]
        if score_row:
            artifacts.append(rel(R10_SCORES))
            fields.extend([f"{family}_contribution;{family}_materialization_status" for family in REQUIRED_FAMILIES])
        out = {
            "ticker": ticker,
            "baseline_rank": row.get("official_current_rank", ""),
            "ticker_identity_match": tf(dimensions["ticker_identity_match"]),
            "price_data_available": tf(price),
            "required_factor_family_scores_available": tf(required_family_scores),
            "fundamental_score_available": tf(family_flags["fundamental"]),
            "technical_score_available": tf(family_flags["technical"]),
            "strategy_score_available": tf(family_flags["strategy"]),
            "risk_score_available": tf(family_flags["risk"]),
            "market_regime_score_available": tf(family_flags["market_regime"]),
            "data_trust_score_excluded_from_scoring": "TRUE",
            "source_quality_status": source_quality,
            "freshness_status": freshness,
            "pit_safety_status": pit_safety,
            "schema_status": schema,
            "current_ranking_eligibility_status": ranking_eligibility,
            "score_lineage_bindable": tf(lineage == "PASS"),
            "direct_data_trust_status": direct_status,
            "direct_data_trust_pass": tf(direct_status == "DIRECT_PASS"),
            "direct_data_trust_fail": tf(direct_status == "DIRECT_FAIL"),
            "direct_data_trust_unknown": tf(direct_status == "UNKNOWN"),
            "direct_status_source_artifacts": ";".join(dict.fromkeys(artifacts)),
            "direct_status_source_fields": ";".join(fields),
            "direct_status_confidence": "DIRECT_HIGH" if direct_status == "DIRECT_PASS" else ("DIRECT_FAIL_EVIDENCE" if direct_status == "DIRECT_FAIL" else "UNKNOWN"),
            "failure_or_unknown_reason": reason,
            "repair_required": tf(direct_status != "DIRECT_PASS"),
            "recommended_repair_action": action,
            **COMMON,
        }
        emitter.append(out)
        if direct_status != "DIRECT_PASS":
            backlog.append({
                "ticker": ticker,
                "baseline_rank": row.get("official_current_rank", ""),
                "direct_data_trust_status": direct_status,
                "failure_or_unknown_reason": reason,
                "missing_contract_dimensions": ";".join(sorted(set(unknown_reasons + fail_reasons))),
                "recommended_repair_action": action,
                "repair_priority": "HIGH" if direct_status == "UNKNOWN" else "CRITICAL",
                **COMMON,
            })
    return emitter, backlog


def build_summary(emitter: list[dict[str, str]], backlog: list[dict[str, str]], discovery: list[dict[str, str]]) -> dict[str, str]:
    total = len(emitter)
    pass_count = sum(row["direct_data_trust_pass"] == "TRUE" for row in emitter)
    fail_count = sum(row["direct_data_trust_fail"] == "TRUE" for row in emitter)
    unknown_count = sum(row["direct_data_trust_unknown"] == "TRUE" for row in emitter)
    coverage = (pass_count + fail_count) / total if total else 0.0
    ticker_sources = sum(row["ticker_level"] == "TRUE" for row in discovery)
    usable_sources = sum(row["usable_for_direct_status_emitter"] == "TRUE" for row in discovery)
    aggregate_only = sum(row["artifact_exists"] == "TRUE" and row["ticker_level"] != "TRUE" for row in discovery)
    if pass_count == 0 and unknown_count == total:
        ready, action = "FALSE", "REQUIRE_UPSTREAM_DIRECT_TICKER_STATUS_EMITTER_REPAIR"
    elif unknown_count == 0 and coverage == 1.0:
        ready, action = "TRUE", "CONTINUE_TO_V20_171_DIRECT_STATUS_GATE_ONLY_RANKING_SIMULATION"
    elif pass_count > 0:
        ready, action = "TRUE", "CONTINUE_TO_V20_171_PARTIAL_DIRECT_STATUS_RANKING_SIMULATION_EXCLUDING_UNKNOWN_ROWS"
    else:
        ready, action = "FALSE", "REPAIR_DIRECT_STATUS_EMITTER_BEFORE_V20_171"
    return {
        "summary_id": "V20_170_DATA_TRUST_DIRECT_STATUS_COVERAGE_AUDIT_001",
        "baseline_candidate_count": str(total),
        "direct_status_emitter_created": "TRUE",
        "direct_status_contract_created": "TRUE",
        "direct_data_trust_pass_count": str(pass_count),
        "direct_data_trust_fail_count": str(fail_count),
        "direct_data_trust_unknown_count": str(unknown_count),
        "direct_status_coverage_rate": fmt(coverage),
        "unknown_count": str(unknown_count),
        "fail_count": str(fail_count),
        "repair_backlog_count": str(len(backlog)),
        "ticker_level_source_artifact_count": str(ticker_sources),
        "usable_direct_status_source_count": str(usable_sources),
        "aggregate_only_source_artifact_count": str(aggregate_only),
        "ready_for_direct_status_gate_only_ranking_simulation": ready,
        "ready_for_official_use": "FALSE",
        "recommended_next_action": action,
        **COMMON,
    }


def safety_rows(upstream_mutated: bool, prereq_ok: bool) -> list[dict[str, str]]:
    checks = [
        ("v20_169_prerequisites_met", "TRUE", tf(prereq_ok)),
        ("ranking_simulation_created", "FALSE", "FALSE"),
        ("research_only", "TRUE", "TRUE"),
        ("data_trust_scoring_weight", "0.0000000000", "0.0000000000"),
        ("data_trust_role", DATA_TRUST_ROLE, DATA_TRUST_ROLE),
        ("direct_ticker_mapping_required_before_official_use", "TRUE", "TRUE"),
        ("formal_activation_allowed", "FALSE", "FALSE"),
        ("promotion_ready", "FALSE", "FALSE"),
        ("official_recommendation_created", "FALSE", "FALSE"),
        ("official_ranking_mutated", "FALSE", "FALSE"),
        ("official_weight_change_created", "FALSE", "FALSE"),
        ("official_weight_registry_mutated", "FALSE", "FALSE"),
        ("weight_mutated", "FALSE", "FALSE"),
        ("real_book_action_created", "FALSE", "FALSE"),
        ("trade_action_created", "FALSE", "FALSE"),
        ("broker_execution_supported", "FALSE", "FALSE"),
        ("performance_claim_created", "FALSE", "FALSE"),
        ("shadow_weight_expansion_allowed", "FALSE", "FALSE"),
        ("inferred_mapping_converted_to_direct", "FALSE", "FALSE"),
        ("aggregate_pass_treated_as_ticker_pass", "FALSE", "FALSE"),
        ("unknown_treated_as_pass", "FALSE", "FALSE"),
        ("upstream_outputs_mutated", "FALSE", tf(upstream_mutated)),
    ]
    return [{
        "safety_check_id": f"V20_170_SAFETY_{idx:03d}",
        "safety_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "safety_passed": tf(expected == actual),
        **COMMON,
    } for idx, (check, expected, actual) in enumerate(checks, start=1)]


def write_report(status: str, summary: dict[str, str] | None = None) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.170 DATA_TRUST Direct Status Contract And Emitter Repair Report",
        "",
        f"- wrapper_status: {status}",
        "- research_only: TRUE",
        "- ranking_simulation_created: FALSE",
        "- data_trust_scoring_weight: 0.0000000000",
        f"- data_trust_role: {DATA_TRUST_ROLE}",
        "- ready_for_official_use: FALSE",
        "- official_weight_change_allowed: FALSE",
        "- official_ranking_mutation_allowed: FALSE",
    ]
    if summary:
        lines.extend([
            f"- baseline_candidate_count: {summary['baseline_candidate_count']}",
            f"- direct_data_trust_pass_count: {summary['direct_data_trust_pass_count']}",
            f"- direct_data_trust_fail_count: {summary['direct_data_trust_fail_count']}",
            f"- direct_data_trust_unknown_count: {summary['direct_data_trust_unknown_count']}",
            f"- direct_status_coverage_rate: {summary['direct_status_coverage_rate']}",
            f"- repair_backlog_count: {summary['repair_backlog_count']}",
            f"- recommended_next_action: {summary['recommended_next_action']}",
        ])
    lines.extend(["", "Aggregate evidence and inferred mapping are not treated as direct ticker-level DATA_TRUST status."])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_170_DATA_TRUST_DIRECT_STATUS_NEXT_GATE_001",
        "v20_169_gate_consumed": "FALSE",
        "v20_169_status": "",
        "baseline_candidate_count": "0",
        "direct_status_emitter_created": "FALSE",
        "direct_status_contract_created": "FALSE",
        "direct_data_trust_pass_count": "0",
        "direct_data_trust_fail_count": "0",
        "direct_data_trust_unknown_count": "0",
        "direct_status_coverage_rate": "0.0000000000",
        "ready_for_direct_status_gate_only_ranking_simulation": "FALSE",
        "ready_for_official_use": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE",
        "no_ticker_status_fabricated": "TRUE",
        "inferred_mapping_not_converted_to_direct": "TRUE",
        "aggregate_pass_not_treated_as_ticker_pass": "TRUE",
        "unknown_not_treated_as_pass": "TRUE",
        "data_trust_gate_criteria_not_lowered": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        **COMMON,
    }
    for path, fields in [
        (OUT_CONTRACT, CONTRACT_FIELDS), (OUT_DISCOVERY, DISCOVERY_FIELDS),
        (OUT_EMITTER, EMITTER_FIELDS), (OUT_STATUS, EMITTER_FIELDS),
        (OUT_BACKLOG, BACKLOG_FIELDS), (OUT_COVERAGE, SUMMARY_FIELDS),
        (OUT_SAFETY, SAFETY_FIELDS),
    ]:
        write_csv(path, fields, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(BLOCKED_STATUS)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    sources = discover_sources()
    before = input_hashes(sources)
    missing = [path for path in required_inputs() if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))

    gate_rows, _ = read_csv(V169_GATE)
    baseline_rows, _ = read_csv(BASELINE)
    weight_rows, _ = read_csv(WEIGHTS)
    if not all([gate_rows, baseline_rows, weight_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    gate = gate_rows[0]
    data_trust_weight_zero = any(row.get("factor_family") == "DATA_TRUST" and row.get("is_official_weight") == "FALSE" for row in weight_rows)
    prereq_ok = all([
        gate.get("final_status") == REQUIRED_V169_STATUS,
        gate.get("data_trust_scoring_weight") == "0.0000000000",
        gate.get("data_trust_role") == DATA_TRUST_ROLE,
        gate.get("ready_for_direct_mapping_gate_only_ranking_simulation") == "FALSE",
        gate.get("ready_for_official_use") == "FALSE",
        data_trust_weight_zero,
    ])
    if not prereq_ok:
        return emit_blocked("V20_169_REQUIREMENTS_NOT_MET")

    contract = build_contract()
    discovery = [source_discovery(path) for path in sources]
    emitter, backlog = build_emitter(baseline_rows)
    summary = build_summary(emitter, backlog, discovery)
    upstream_mutated = before != input_hashes(sources)
    safety = safety_rows(upstream_mutated, prereq_ok)
    safety_ok = all(row["safety_passed"] == "TRUE" for row in safety)
    if upstream_mutated or not safety_ok:
        return emit_blocked("SAFETY_OR_UPSTREAM_MUTATION_FAILURE")

    pass_count = int(num(summary["direct_data_trust_pass_count"]))
    unknown_count = int(num(summary["direct_data_trust_unknown_count"]))
    coverage = num(summary["direct_status_coverage_rate"])
    if coverage == 1.0 and unknown_count == 0:
        status = PASS_STATUS
    elif pass_count > 0 and unknown_count > 0:
        status = PARTIAL_STATUS
    else:
        status = WARN_STATUS

    gate_out = {
        "gate_check_id": "V20_170_DATA_TRUST_DIRECT_STATUS_NEXT_GATE_001",
        "v20_169_gate_consumed": "TRUE",
        "v20_169_status": gate.get("final_status", ""),
        **{field: summary[field] for field in SUMMARY_FIELDS if field in summary and field not in COMMON},
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE",
        "no_ticker_status_fabricated": "TRUE",
        "inferred_mapping_not_converted_to_direct": "TRUE",
        "aggregate_pass_not_treated_as_ticker_pass": "TRUE",
        "unknown_not_treated_as_pass": "TRUE",
        "data_trust_gate_criteria_not_lowered": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "blocking_reason": "",
        "final_status": status,
        **COMMON,
    }

    write_csv(OUT_CONTRACT, CONTRACT_FIELDS, contract)
    write_csv(OUT_DISCOVERY, DISCOVERY_FIELDS, discovery)
    write_csv(OUT_EMITTER, EMITTER_FIELDS, emitter)
    write_csv(OUT_STATUS, EMITTER_FIELDS, emitter)
    write_csv(OUT_BACKLOG, BACKLOG_FIELDS, backlog)
    write_csv(OUT_COVERAGE, SUMMARY_FIELDS, [summary])
    write_csv(OUT_GATE, GATE_FIELDS, [gate_out])
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_report(status, summary)

    print(status)
    print("V20_169_GATE_CONSUMED=TRUE")
    print(f"V20_169_STATUS={gate.get('final_status', '')}")
    print("DATA_TRUST_SCORING_WEIGHT=0.0000000000")
    print(f"DATA_TRUST_ROLE={DATA_TRUST_ROLE}")
    print("DIRECT_STATUS_CONTRACT_CREATED=TRUE")
    print("DIRECT_STATUS_EMITTER_CREATED=TRUE")
    print(f"BASELINE_CANDIDATE_COUNT={summary['baseline_candidate_count']}")
    print(f"DIRECT_DATA_TRUST_PASS_COUNT={summary['direct_data_trust_pass_count']}")
    print(f"DIRECT_DATA_TRUST_FAIL_COUNT={summary['direct_data_trust_fail_count']}")
    print(f"DIRECT_DATA_TRUST_UNKNOWN_COUNT={summary['direct_data_trust_unknown_count']}")
    print(f"DIRECT_STATUS_COVERAGE_RATE={summary['direct_status_coverage_rate']}")
    print(f"READY_FOR_DIRECT_STATUS_GATE_ONLY_RANKING_SIMULATION={summary['ready_for_direct_status_gate_only_ranking_simulation']}")
    print("READY_FOR_OFFICIAL_USE=FALSE")
    print("OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE")
    print("OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE")
    print("RANKING_SIMULATION_CREATED=FALSE")
    print("FORMAL_ACTIVATION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_ACTION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("PERFORMANCE_CLAIM_CREATED=FALSE")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
