from __future__ import annotations

import csv
import json
import math
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
EVIDENCE = ROOT / "outputs" / "v20" / "evidence"
SCAN_DIRS = [CONSOLIDATION, READ_CENTER, OPS]

STAGE = "V20.84_CERTIFIED_MULTI_PATH_EVIDENCE_EXPORT_LAYER"
PASS_STATUS = "PASS_V20_84_CERTIFIED_MULTI_PATH_EVIDENCE_EXPORT"
GAPS_STATUS = "PASS_V20_84_CERTIFIED_EVIDENCE_EXPORT_WITH_GAPS"
R2_PASS_STATUS = "PASS_V20_84_R2_REQUIRED_EVIDENCE_PATHS_INTEGRATED"
R2_PARTIAL_STATUS = "PARTIAL_PASS_V20_84_R2_REQUIRED_PATHS_ATTACHED_WITH_BLOCKERS"
NO_EVIDENCE_STATUS = "BLOCKED_V20_84_NO_USABLE_STRUCTURED_EVIDENCE"
UNSAFE_STATUS = "BLOCKED_V20_84_UNSAFE_OFFICIAL_OR_TRADE_ARTIFACT_DETECTED"
PROXY_STATUS = "PROXY_TECHNICAL_RETURN_NOT_CERTIFIED_STRATEGY_ALPHA"

ALLOWED_COMPONENT_TYPES = {
    "FACTOR",
    "ENTRY_STRATEGY",
    "EXIT_STRATEGY",
    "POSITION_SIZING",
    "PORTFOLIO_MODEL",
    "BENCHMARK_MODEL",
    "ETF_ROTATION",
    "LIVE_OBSERVATION",
    "PROMOTION_GATE",
}
ALLOWED_EVIDENCE_PATHS = {
    "HISTORICAL_BACKTEST",
    "RANDOM_ASOF_BACKTEST",
    "LIVE_OBSERVATION",
    "REGIME_CONDITIONED",
    "DOWNSIDE_RISK",
    "PORTFOLIO_BACKTEST",
    "BENCHMARK_COMPARISON",
    "ETF_ROTATION_EVIDENCE",
    "PROMOTION_READINESS",
}
EVIDENCE_FIELDS = [
    "component_name",
    "component_type",
    "evidence_path",
    "source_stage",
    "source_file",
    "source_run_id",
    "metric_name",
    "metric_value",
    "metric_unit",
    "evaluation_window",
    "benchmark_name",
    "benchmark_return",
    "excess_return",
    "drawdown",
    "hit_rate",
    "coverage_status",
    "certification_status",
    "certification_reason",
    "usable_for_v20_82",
    "research_only",
    "official_recommendation_created",
    "official_weight_mutated",
    "trade_action_created",
]
AUDIT_FIELDS = [
    "input_family",
    "expected_stage",
    "candidate_file",
    "detected_status",
    "row_count",
    "required_or_optional",
    "schema_valid",
    "semantic_valid",
    "usable_evidence_count",
    "binding_quality",
    "reject_reason",
]
COVERAGE_FIELDS = [
    "component_name",
    "component_type",
    "historical_backtest_found",
    "random_asof_found",
    "live_observation_found",
    "regime_conditioned_found",
    "downside_risk_found",
    "portfolio_backtest_found",
    "benchmark_comparison_found",
    "etf_rotation_found",
    "usable_evidence_count",
    "required_evidence_count",
    "evidence_coverage_ratio",
    "has_any_usable_evidence",
    "v20_82_usable",
    "blocking_reason",
]
R2_DETAIL_FIELDS = [
    "integration_category",
    "path_id",
    "required_level",
    "manifest_current_status",
    "expected_source_file",
    "expected_current_alias",
    "bound_source_file",
    "source_status",
    "v20_82_r5_validation_status",
    "attached_row_count",
    "certified_row_count",
    "partial_row_count",
    "blocked_row_count",
    "integration_status",
    "integration_blocker_reason",
    "research_only",
    "official_recommendation_created",
    "official_weight_mutated",
    "trade_action_created",
]
OUTPUTS = {
    "evidence": CONSOLIDATION / "V20_84_CERTIFIED_MULTI_PATH_EVIDENCE_TABLE.csv",
    "audit": CONSOLIDATION / "V20_84_EVIDENCE_INPUT_BINDING_AUDIT.csv",
    "coverage": CONSOLIDATION / "V20_84_COMPONENT_EVIDENCE_COVERAGE_TABLE.csv",
    "report": READ_CENTER / "V20_84_CERTIFIED_MULTI_PATH_EVIDENCE_EXPORT_REPORT.md",
    "manifest": OPS / "V20_84_CERTIFIED_MULTI_PATH_EVIDENCE_EXPORT_MANIFEST.json",
}
R2_DETAIL = EVIDENCE / "V20_84_R2_REQUIRED_PATH_INTEGRATION_DETAIL.csv"
R2_DETAIL_ALIAS = EVIDENCE / "V20_CURRENT_REQUIRED_PATH_INTEGRATION_DETAIL.csv"
V20_89_REQUIRED_EVIDENCE_MANIFEST = EVIDENCE / "V20_CURRENT_REQUIRED_EVIDENCE_PATH_MANIFEST.csv"
V20_82_R5_DETAIL = EVIDENCE / "V20_CURRENT_MULTI_PATH_VALIDATION_DETAIL.csv"
V20_90_ETF_ROTATION_EVIDENCE = EVIDENCE / "V20_CURRENT_ETF_ROTATION_EVIDENCE_TABLE.csv"
V20_91_MULTI_WINDOW_STRATEGY_EVIDENCE = EVIDENCE / "V20_CURRENT_MULTI_WINDOW_STRATEGY_EVIDENCE_MATRIX.csv"
V20_86_REGIME_EVIDENCE = CONSOLIDATION / "V20_CURRENT_REGIME_CONDITIONED_EVIDENCE_EXPORT.csv"
V20_87_DOWNSIDE_EVIDENCE = CONSOLIDATION / "V20_CURRENT_DOWNSIDE_RISK_EVIDENCE_EXPORT.csv"
V20_88_BENCHMARK_EVIDENCE = CONSOLIDATION / "V20_CURRENT_CERTIFIED_BENCHMARK_COMPARISON_EVIDENCE_EXPORT.csv"
V20_93_ACCEPTANCE_PROOF_REPAIR = EVIDENCE / "V20_CURRENT_ACCEPTANCE_PROOF_EVIDENCE_REPAIR.csv"
V20_93_RANKING_DELTA_REPAIR = EVIDENCE / "V20_CURRENT_RANKING_DELTA_DIAGNOSTIC_EVIDENCE_REPAIR.csv"
ALIASES = {
    path: path.with_name(path.name.replace("V20_84_", "V20_CURRENT_", 1))
    for path in OUTPUTS.values()
}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_run_id() -> str:
    return "V20_84_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def parse_float(value: object) -> float | None:
    text = clean(value).replace(",", "")
    if not text or text.upper() in {"NA", "N/A", "NONE", "NULL", "TRUE", "FALSE"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def fmt(value: object) -> str:
    number = parse_float(value)
    return "NA" if number is None else f"{number:.6f}"


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str], str]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = [{k: clean(v) for k, v in row.items()} for row in reader]
            return rows, list(reader.fieldnames or []), ""
    except Exception as exc:  # pragma: no cover - defensive audit path
        return [], [], str(exc)


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: clean(row.get(field, "")) for field in fields})


def source_stage(path: Path) -> str:
    name = path.name.upper()
    for token in [
        "V20_39_R2",
        "V20_39_R1",
        "V20_79A_R1",
        "V20_79A",
        "V20_37",
        "V20_38",
        "V20_39",
        "V20_40",
        "V20_57",
        "V20_64",
        "V20_65",
        "V20_66",
        "V20_82",
        "V20_83",
    ]:
        if token in name:
            return token
    return "UNKNOWN"


def is_rejected_file(path: Path) -> tuple[bool, str]:
    name = path.name.upper()
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return True, "READABLE_REPORT_OR_TEXT_ONLY"
    reject_tokens = [
        "REQUIRED_OUTPUT_CHECKS",
        "MANIFEST",
        "HASH_LEDGER",
        "SOURCE_HASH",
        "INPUT_HASH",
        "OUTPUT_HASH",
        "READ_FIRST",
        "README",
        "REPORT",
        "STATUS_SUMMARY",
        "DIAGNOSTIC",
    ]
    for token in reject_tokens:
        if token in name:
            return True, f"REJECTED_{token}"
    if any(token in name for token in ["BROKER", "TRADE_ORDER", "ORDER_TICKET", "EXECUTION_TICKET"]):
        return True, "UNSAFE_OFFICIAL_OR_TRADE_ARTIFACT"
    if "OFFICIAL_RECOMMENDATION" in name:
        return True, "OFFICIAL_RECOMMENDATION_ARTIFACT_REJECTED"
    return False, ""


def non_placeholder(value: object) -> bool:
    text = clean(value).upper()
    return bool(text) and text not in {"NA", "N/A", "NONE", "NULL", "PLACEHOLDER", "TBD"}


def has_blocking_token(value: object) -> bool:
    text = clean(value).upper()
    return any(token in text for token in ["INSUFFICIENT", "DESIGN_ONLY", "NOT_READY", "RESEARCH_ONLY_GUARDRAIL", "MISSING", "BLOCKED"])


def has_exact_positive_etf_certification(row: dict[str, str]) -> bool:
    positive_values = {"CERTIFIED_ROTATION_BACKTEST", "CERTIFIED_ETF_ROTATION_EVIDENCE"}
    approved_columns = {
        "certification_status",
        "rotation_backtest_certification_status",
        "etf_rotation_certification_status",
        "etf_rotation_backtest_certification_status",
    }
    if any(has_blocking_token(value) for value in row.values()):
        return False
    for key, value in row.items():
        if clean(key).lower() not in approved_columns:
            continue
        text = clean(value).upper()
        if text in positive_values:
            return True
    return False


R2_CATEGORY_BY_PATH_ID = {
    "certified_etf_rotation_evidence": "etf_rotation_evidence",
    "multi_window_strategy_evidence": "multi_window_strategy_evidence",
    "regime_conditioned_evidence": "regime_conditioned_evidence",
    "downside_risk_evidence": "downside_risk_evidence",
    "benchmark_comparison_evidence": "benchmark_comparison_evidence",
    "score_lineage_evidence": "score_lineage_evidence",
    "ranking_delta_diagnostic_evidence": "ranking_delta_diagnostic_evidence",
    "acceptance_proof_evidence": "acceptance_proof_evidence",
}
R2_SOURCE_BY_PATH_ID = {
    "certified_etf_rotation_evidence": V20_90_ETF_ROTATION_EVIDENCE,
    "multi_window_strategy_evidence": V20_91_MULTI_WINDOW_STRATEGY_EVIDENCE,
    "regime_conditioned_evidence": V20_86_REGIME_EVIDENCE,
    "downside_risk_evidence": V20_87_DOWNSIDE_EVIDENCE,
    "benchmark_comparison_evidence": V20_88_BENCHMARK_EVIDENCE,
    "score_lineage_evidence": CONSOLIDATION / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    "ranking_delta_diagnostic_evidence": V20_93_RANKING_DELTA_REPAIR,
    "acceptance_proof_evidence": V20_93_ACCEPTANCE_PROOF_REPAIR,
}
R2_CERTIFICATION_FIELDS = {
    "certification_status",
    "benchmark_comparison_certification_status",
    "downside_risk_certification_status",
    "regime_conditioned_certification_status",
    "etf_rotation_certification_status",
    "multi_window_strategy_certification_status",
}
R2_REJECT_TOKENS = {
    "BLOCKED",
    "DESIGN_ONLY",
    "INSUFFICIENT",
    "MISSING",
    "NOT_CERTIFIED",
    "NOT_READY",
    "PARTIAL",
    "RESEARCH_ONLY_GUARDRAIL",
    "UNCERTIFIED",
}


def r2_read_csv(path: Path) -> tuple[list[dict[str, str]], list[str], str]:
    if not path.exists():
        return [], [], "MISSING_FILE"
    if path.stat().st_size == 0:
        return [], [], "EMPTY_FILE"
    rows, fields, error = read_csv(path)
    if error:
        return [], [], "UNREADABLE_FILE"
    if not fields:
        return [], [], "MALFORMED_CSV"
    return rows, fields, "OK"


def r2_structured_certified(row: dict[str, str]) -> bool:
    for field, value in row.items():
        lower = field.lower()
        text = clean(value).upper()
        if lower not in R2_CERTIFICATION_FIELDS and not lower.endswith("_certification_status"):
            continue
        if "reason" in lower or "note" in lower:
            continue
        if not text or any(token in text for token in R2_REJECT_TOKENS):
            continue
        if text == "CERTIFIED" or text == "TRUE" or text.startswith("CERTIFIED_"):
            return True
    return False


def r2_partial(row: dict[str, str]) -> bool:
    return any("PARTIAL" in clean(value).upper() for key, value in row.items() if "status" in key.lower())


def r2_blocked(row: dict[str, str]) -> bool:
    return any("BLOCKED" in clean(value).upper() for key, value in row.items() if "status" in key.lower() or "reason" in key.lower())


def r2_manifest_rows() -> list[dict[str, str]]:
    rows, _, status = r2_read_csv(V20_89_REQUIRED_EVIDENCE_MANIFEST)
    if status != "OK":
        return []
    return [row for row in rows if clean(row.get("path_id")) in R2_CATEGORY_BY_PATH_ID]


def r2_r5_index() -> dict[str, dict[str, str]]:
    rows, _, status = r2_read_csv(V20_82_R5_DETAIL)
    if status != "OK":
        return {}
    return {clean(row.get("validation_category")): row for row in rows if clean(row.get("validation_category"))}


def build_r2_integration_detail() -> tuple[list[dict[str, str]], str, dict[str, object]]:
    manifest_rows = r2_manifest_rows()
    r5_index = r2_r5_index()
    detail: list[dict[str, str]] = []
    if not manifest_rows:
        for path_id, category in R2_CATEGORY_BY_PATH_ID.items():
            required_level = "OPTIONAL" if path_id == "ranking_delta_diagnostic_evidence" else "REQUIRED"
            status = "WARN" if required_level == "OPTIONAL" else "BLOCKED"
            detail.append({
                "integration_category": category,
                "path_id": path_id,
                "required_level": required_level,
                "manifest_current_status": "MISSING_MANIFEST",
                "expected_source_file": "NA",
                "expected_current_alias": "NA",
                "bound_source_file": "NA",
                "source_status": "MISSING_MANIFEST",
                "v20_82_r5_validation_status": "MISSING_R5_DETAIL",
                "attached_row_count": "0",
                "certified_row_count": "0",
                "partial_row_count": "0",
                "blocked_row_count": "0",
                "integration_status": status,
                "integration_blocker_reason": f"{category.upper()}_V20_89_REQUIRED_EVIDENCE_MANIFEST_MISSING",
                "research_only": "TRUE",
                "official_recommendation_created": "FALSE",
                "official_weight_mutated": "FALSE",
                "trade_action_created": "FALSE",
            })
    for manifest_row in manifest_rows:
        path_id = clean(manifest_row.get("path_id"))
        category = R2_CATEGORY_BY_PATH_ID[path_id]
        required_level = clean(manifest_row.get("required_level")) or ("OPTIONAL" if path_id == "ranking_delta_diagnostic_evidence" else "REQUIRED")
        manifest_status = clean(manifest_row.get("current_status")) or "UNKNOWN"
        source = R2_SOURCE_BY_PATH_ID[path_id]
        rows, _, source_status = r2_read_csv(source)
        attached = len(rows) if source_status == "OK" else 0
        certified = sum(1 for row in rows if r2_structured_certified(row)) if source_status == "OK" else 0
        partial = sum(1 for row in rows if r2_partial(row) and not r2_structured_certified(row)) if source_status == "OK" else 0
        blocked = sum(1 for row in rows if r2_blocked(row)) if source_status == "OK" else 0
        r5_status = clean(r5_index.get(category, {}).get("validation_status")) or "MISSING_R5_DETAIL"
        integration_status = "INTEGRATED"
        blocker = "NA"
        if source_status != "OK":
            integration_status = "WARN" if required_level == "OPTIONAL" else "BLOCKED"
            blocker = f"{category.upper()}_MISSING_REQUIRED_PATH:{source_status}"
        elif attached == 0:
            integration_status = "WARN" if required_level == "OPTIONAL" else "BLOCKED"
            blocker = f"{category.upper()}_NO_ATTACHED_ROWS"
        elif certified > 0:
            integration_status = "INTEGRATED"
        elif partial > 0:
            integration_status = "WARN" if required_level == "OPTIONAL" else "BLOCKED"
            blocker = f"{category.upper()}_PARTIAL_ATTACHED_NOT_CERTIFIED"
        else:
            integration_status = "WARN" if required_level == "OPTIONAL" else "BLOCKED"
            blocker = f"{category.upper()}_STRUCTURED_CERTIFICATION_MISSING"
        if manifest_status == "BLOCKED" and required_level != "OPTIONAL" and certified == 0:
            integration_status = "BLOCKED"
            blocker = f"{category.upper()}_{clean(manifest_row.get('missing_reason')) or 'MANIFEST_BLOCKED_REQUIRED_PATH'}"
        if manifest_status == "WARN" and integration_status != "INTEGRATED":
            integration_status = "WARN"
            blocker = f"{category.upper()}_{clean(manifest_row.get('missing_reason')) or blocker}"
        detail.append({
            "integration_category": category,
            "path_id": path_id,
            "required_level": required_level,
            "manifest_current_status": manifest_status,
            "expected_source_file": clean(manifest_row.get("expected_source_file")) or "NA",
            "expected_current_alias": clean(manifest_row.get("expected_current_alias")) or "NA",
            "bound_source_file": rel(source),
            "source_status": source_status,
            "v20_82_r5_validation_status": r5_status,
            "attached_row_count": str(attached),
            "certified_row_count": str(certified),
            "partial_row_count": str(partial),
            "blocked_row_count": str(blocked),
            "integration_status": integration_status,
            "integration_blocker_reason": blocker,
            "research_only": "TRUE",
            "official_recommendation_created": "FALSE",
            "official_weight_mutated": "FALSE",
            "trade_action_created": "FALSE",
        })
    required_blocked = any(row["required_level"] != "OPTIONAL" and row["integration_status"] == "BLOCKED" for row in detail)
    status = R2_PARTIAL_STATUS if required_blocked else R2_PASS_STATUS
    meta = {
        "v20_89_consumed": bool(manifest_rows),
        "v20_82_r5_consumed": bool(r5_index),
        "v20_90_consumed": any(row["path_id"] == "certified_etf_rotation_evidence" and int(row["attached_row_count"]) > 0 for row in detail),
        "v20_91_consumed": any(row["path_id"] == "multi_window_strategy_evidence" and int(row["attached_row_count"]) > 0 for row in detail),
        "integration_category_count": len(detail),
        "integrated_category_count": sum(row["integration_status"] == "INTEGRATED" for row in detail),
        "blocked_category_count": sum(row["integration_status"] == "BLOCKED" for row in detail),
        "warned_category_count": sum(row["integration_status"] == "WARN" for row in detail),
        "readable_regime_evidence_count": r2_category_count(detail, "regime_conditioned_evidence"),
        "readable_downside_risk_evidence_count": r2_category_count(detail, "downside_risk_evidence"),
        "readable_benchmark_comparison_evidence_count": r2_category_count(detail, "benchmark_comparison_evidence"),
        "readable_acceptance_proof_evidence_count": r2_category_count(detail, "acceptance_proof_evidence"),
        "readable_ranking_delta_diagnostic_evidence_count": r2_category_count(detail, "ranking_delta_diagnostic_evidence", "attached_row_count"),
        "missing_required_evidence_categories": [
            row["integration_category"]
            for row in detail
            if row["required_level"] != "OPTIONAL" and row["integration_status"] == "BLOCKED"
        ],
    }
    return detail, status, meta


def r2_category_count(detail: list[dict[str, str]], category: str, field: str = "certified_row_count") -> int:
    for row in detail:
        if row.get("integration_category") == category:
            try:
                return int(row.get(field) or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def required_columns_for(path: Path) -> set[str]:
    name = path.name.upper()
    if "V20_37_ENTRY_STRATEGY_BENCHMARK_RELATIVE_SUMMARY" in name:
        return {"entry_strategy_id", "forward_window", "average_ticker_return", "average_benchmark_relative_return_vs_qqq", "win_rate_vs_qqq"}
    if "V20_38_FACTOR_EFFECTIVENESS_METRICS" in name:
        return {"factor_name", "forward_window", "rank_corr_factor_vs_qqq_relative_return", "high_factor_average_benchmark_relative_return_vs_qqq", "high_factor_bucket_win_rate_vs_qqq"}
    if "V20_39_R1_SHADOW_BENCHMARK_RELATIVE_SUMMARY" in name:
        return {"candidate_weight_set_id", "forward_window", "average_ticker_return", "average_benchmark_relative_return_vs_qqq", "win_rate_vs_qqq"}
    if "V20_39_R2_SHADOW_ENTRY_STRATEGY_BENCHMARK_RELATIVE_SUMMARY" in name:
        return {"candidate_weight_set_id", "entry_strategy_id", "forward_window", "average_ticker_return", "average_benchmark_relative_return_vs_qqq", "win_rate_vs_qqq"}
    if "V20_40_PORTFOLIO_BENCHMARK_RELATIVE_RETURNS" in name:
        return {"portfolio_policy_id", "entry_strategy_id", "forward_window", "average_net_portfolio_return", "average_net_benchmark_relative_return_vs_qqq", "win_rate_vs_qqq"}
    if "V20_64_MULTI_RUN_EVIDENCE_ACCUMULATION_SUMMARY" in name:
        return {"run_id", "effective_source_run_count", "evidence_sufficiency_status"}
    if "V20_65_PROPOSAL_PROMOTION_READINESS_GATE" in name:
        return {"proposal_id", "effective_source_run_count", "readiness_state"}
    if "V20_66_CANDIDATE_WEIGHT_UPDATE_DRY_RUN" in name:
        return {"factor_or_strategy_id", "candidate_weight_delta", "candidate_applied_to_official_ranking"}
    if "V20_82_BENCHMARK_STRATEGY_COMPARISON" in name:
        return {"strategy_name", "return_evidence_status", "strategy_return", "benchmark_name", "benchmark_return", "excess_return"}
    if "V20_82_STRATEGY_MULTI_PATH_VALIDATION_TABLE" in name:
        return {"strategy_name", "return_evidence_status", "model_return", "benchmark_return", "excess_return"}
    if "V20_82_ETF_ROTATION_SHADOW_SIGNAL_TABLE" in name or "V20_79A" in name:
        return {"etf_symbol", "rotation_shadow_score"}
    return set()


def schema_valid_for(path: Path, fields: list[str]) -> bool:
    required = required_columns_for(path)
    return bool(required) and required.issubset(set(fields))


def evidence_row(
    *,
    component_name: str,
    component_type: str,
    evidence_path: str,
    source: Path,
    run_id: str,
    metric_name: str,
    metric_value: object,
    metric_unit: str,
    evaluation_window: str = "NA",
    benchmark_name: str = "NA",
    benchmark_return: object = "NA",
    excess_return: object = "NA",
    drawdown: object = "NA",
    hit_rate: object = "NA",
    status: str = "CERTIFIED",
    reason: str = "CERTIFIED_STRUCTURED_SOURCE_METRIC",
    usable: bool = True,
    coverage: str = "FOUND",
) -> dict[str, str]:
    metric_ok = non_placeholder(metric_value) and parse_float(metric_value) is not None
    final_usable = usable and metric_ok and status == "CERTIFIED"
    final_status = status if final_usable else "NOT_USABLE"
    final_reason = reason if metric_ok or status != "CERTIFIED" or not usable else "MISSING_OR_PLACEHOLDER_METRIC_VALUE"
    return {
        "component_name": component_name,
        "component_type": component_type if component_type in ALLOWED_COMPONENT_TYPES else "LIVE_OBSERVATION",
        "evidence_path": evidence_path if evidence_path in ALLOWED_EVIDENCE_PATHS else "LIVE_OBSERVATION",
        "source_stage": source_stage(source),
        "source_file": rel(source),
        "source_run_id": run_id,
        "metric_name": metric_name,
        "metric_value": fmt(metric_value),
        "metric_unit": metric_unit,
        "evaluation_window": clean(evaluation_window) or "NA",
        "benchmark_name": clean(benchmark_name) or "NA",
        "benchmark_return": fmt(benchmark_return),
        "excess_return": fmt(excess_return),
        "drawdown": fmt(drawdown),
        "hit_rate": fmt(hit_rate),
        "coverage_status": coverage,
        "certification_status": final_status,
        "certification_reason": final_reason,
        "usable_for_v20_82": tf(final_usable),
        "research_only": "TRUE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
    }


def rejected_evidence_row(source: Path, run_id: str, reason: str) -> dict[str, str]:
    return evidence_row(
        component_name=source.stem,
        component_type="LIVE_OBSERVATION",
        evidence_path="LIVE_OBSERVATION",
        source=source,
        run_id=run_id,
        metric_name="NA",
        metric_value="NA",
        metric_unit="NA",
        status="NOT_USABLE",
        reason=reason,
        usable=False,
        coverage="UNUSABLE",
    )


def add_audit(
    rows: list[dict[str, str]],
    *,
    input_family: str,
    expected_stage: str,
    candidate_file: Path,
    detected_status: str,
    row_count: int,
    required_or_optional: str,
    schema_valid: bool,
    semantic_valid: bool,
    usable_count: int,
    binding_quality: str,
    reject_reason: str = "",
) -> None:
    rows.append({
        "input_family": input_family,
        "expected_stage": expected_stage,
        "candidate_file": rel(candidate_file),
        "detected_status": detected_status,
        "row_count": str(row_count),
        "required_or_optional": required_or_optional,
        "schema_valid": tf(schema_valid),
        "semantic_valid": tf(semantic_valid),
        "usable_evidence_count": str(usable_count),
        "binding_quality": binding_quality,
        "reject_reason": reject_reason or "NA",
    })


def csv_files() -> list[Path]:
    files: list[Path] = []
    for directory in SCAN_DIRS:
        if directory.exists():
            files.extend(path for path in directory.iterdir() if path.is_file())
    return sorted(files)


def collect_evidence(run_id: str) -> tuple[list[dict[str, str]], list[dict[str, str]], bool]:
    evidence: list[dict[str, str]] = []
    audit: list[dict[str, str]] = []
    unsafe = False
    preferred_tokens = (
        "V20_37",
        "V20_38",
        "V20_39",
        "V20_40",
        "V20_57",
        "V20_64",
        "V20_65",
        "V20_66",
        "V20_79A",
        "V20_82",
        "V20_83",
    )
    for path in csv_files():
        name = path.name.upper()
        if not any(token in name for token in preferred_tokens):
            continue
        rejected, reject_reason = is_rejected_file(path)
        if rejected:
            if reject_reason == "UNSAFE_OFFICIAL_OR_TRADE_ARTIFACT":
                unsafe = True
            evidence.append(rejected_evidence_row(path, run_id, reject_reason))
            add_audit(
                audit,
                input_family="REJECTED_GENERIC_OR_UNSAFE_INPUT",
                expected_stage=source_stage(path),
                candidate_file=path,
                detected_status="REJECTED",
                row_count=0,
                required_or_optional="OPTIONAL",
                schema_valid=False,
                semantic_valid=False,
                usable_count=0,
                binding_quality="REJECTED",
                reject_reason=reject_reason,
            )
            continue
        if path.suffix.lower() != ".csv":
            continue
        rows, fields, error = read_csv(path)
        produced_before = len(evidence)
        if error:
            add_audit(
                audit,
                input_family="STRUCTURED_INPUT",
                expected_stage=source_stage(path),
                candidate_file=path,
                detected_status="UNREADABLE",
                row_count=0,
                required_or_optional="OPTIONAL",
                schema_valid=False,
                semantic_valid=False,
                usable_count=0,
                binding_quality="UNUSABLE",
                reject_reason=error,
            )
            continue
        if "V20_37_ENTRY_STRATEGY_BENCHMARK_RELATIVE_SUMMARY" in name:
            for row in rows:
                evidence.append(evidence_row(
                    component_name=row.get("entry_strategy_id", "UNKNOWN_ENTRY_STRATEGY"),
                    component_type="ENTRY_STRATEGY",
                    evidence_path="HISTORICAL_BACKTEST",
                    source=path,
                    run_id=run_id,
                    metric_name="average_ticker_return",
                    metric_value=row.get("average_ticker_return"),
                    metric_unit="RETURN_DECIMAL",
                    evaluation_window=row.get("forward_window", "NA"),
                    benchmark_name="QQQ",
                    excess_return=row.get("average_benchmark_relative_return_vs_qqq"),
                    hit_rate=row.get("win_rate_vs_qqq"),
                ))
        elif "V20_38_FACTOR_EFFECTIVENESS_METRICS" in name:
            for row in rows:
                evidence.append(evidence_row(
                    component_name=row.get("factor_name", "UNKNOWN_FACTOR"),
                    component_type="FACTOR",
                    evidence_path="HISTORICAL_BACKTEST",
                    source=path,
                    run_id=run_id,
                    metric_name="rank_corr_factor_vs_qqq_relative_return",
                    metric_value=row.get("rank_corr_factor_vs_qqq_relative_return"),
                    metric_unit="CORRELATION",
                    evaluation_window=row.get("forward_window", "NA"),
                    benchmark_name="QQQ",
                    excess_return=row.get("high_factor_average_benchmark_relative_return_vs_qqq"),
                    hit_rate=row.get("high_factor_bucket_win_rate_vs_qqq"),
                ))
        elif "V20_39_R1_SHADOW_BENCHMARK_RELATIVE_SUMMARY" in name:
            for row in rows:
                evidence.append(evidence_row(
                    component_name=row.get("candidate_weight_set_id", "SHADOW_WEIGHT_RECOMPUTE"),
                    component_type="FACTOR",
                    evidence_path="RANDOM_ASOF_BACKTEST",
                    source=path,
                    run_id=run_id,
                    metric_name="average_ticker_return",
                    metric_value=row.get("average_ticker_return"),
                    metric_unit="RETURN_DECIMAL",
                    evaluation_window=row.get("forward_window", "NA"),
                    benchmark_name="QQQ",
                    excess_return=row.get("average_benchmark_relative_return_vs_qqq"),
                    hit_rate=row.get("win_rate_vs_qqq"),
                ))
        elif "V20_39_R2_SHADOW_ENTRY_STRATEGY_BENCHMARK_RELATIVE_SUMMARY" in name:
            for row in rows:
                name_part = row.get("entry_strategy_id", "UNKNOWN_ENTRY_STRATEGY")
                evidence.append(evidence_row(
                    component_name=f"{row.get('candidate_weight_set_id', 'SHADOW')}:{name_part}",
                    component_type="ENTRY_STRATEGY",
                    evidence_path="RANDOM_ASOF_BACKTEST",
                    source=path,
                    run_id=run_id,
                    metric_name="average_ticker_return",
                    metric_value=row.get("average_ticker_return"),
                    metric_unit="RETURN_DECIMAL",
                    evaluation_window=row.get("forward_window", "NA"),
                    benchmark_name="QQQ",
                    excess_return=row.get("average_benchmark_relative_return_vs_qqq"),
                    hit_rate=row.get("win_rate_vs_qqq"),
                ))
        elif "V20_40_PORTFOLIO_BENCHMARK_RELATIVE_RETURNS" in name:
            for row in rows:
                component = f"{row.get('portfolio_policy_id', 'PORTFOLIO')}:{row.get('entry_strategy_id', 'UNKNOWN')}"
                evidence.append(evidence_row(
                    component_name=component,
                    component_type="PORTFOLIO_MODEL",
                    evidence_path="PORTFOLIO_BACKTEST",
                    source=path,
                    run_id=run_id,
                    metric_name="average_net_portfolio_return",
                    metric_value=row.get("average_net_portfolio_return"),
                    metric_unit="RETURN_DECIMAL",
                    evaluation_window=row.get("forward_window", "NA"),
                    benchmark_name="QQQ",
                    excess_return=row.get("average_net_benchmark_relative_return_vs_qqq"),
                    hit_rate=row.get("win_rate_vs_qqq"),
                ))
        elif "V20_64_MULTI_RUN_EVIDENCE_ACCUMULATION_SUMMARY" in name:
            for row in rows:
                reason = row.get("evidence_sufficiency_status", "STATUS_ONLY_NOT_CERTIFIED_PERFORMANCE_EVIDENCE")
                evidence.append(evidence_row(
                    component_name="V20_64_MULTI_RUN_EVIDENCE_ACCUMULATION",
                    component_type="LIVE_OBSERVATION",
                    evidence_path="LIVE_OBSERVATION",
                    source=path,
                    run_id=row.get("run_id") or run_id,
                    metric_name="effective_source_run_count",
                    metric_value=row.get("effective_source_run_count"),
                    metric_unit="COUNT",
                    status="NOT_USABLE",
                    reason="INSUFFICIENT_MULTI_RUN_HISTORY" if has_blocking_token(reason) else "STATUS_ONLY_NOT_CERTIFIED_PERFORMANCE_EVIDENCE",
                    usable=False,
                    coverage="UNUSABLE",
                ))
        elif "V20_65_PROPOSAL_PROMOTION_READINESS_GATE" in name:
            for row in rows:
                reason = row.get("readiness_state", "STATUS_ONLY_NOT_CERTIFIED_PERFORMANCE_EVIDENCE")
                evidence.append(evidence_row(
                    component_name=row.get("proposal_id", "PROMOTION_PROPOSAL"),
                    component_type="PROMOTION_GATE",
                    evidence_path="PROMOTION_READINESS",
                    source=path,
                    run_id=run_id,
                    metric_name="effective_source_run_count",
                    metric_value=row.get("effective_source_run_count"),
                    metric_unit="COUNT",
                    status="NOT_USABLE",
                    reason="INSUFFICIENT_MULTI_RUN_HISTORY" if has_blocking_token(reason) else "STATUS_ONLY_NOT_CERTIFIED_PERFORMANCE_EVIDENCE",
                    usable=False,
                    coverage="UNUSABLE",
                ))
        elif "V20_66_CANDIDATE_WEIGHT_UPDATE_DRY_RUN" in name:
            for row in rows:
                delta = parse_float(row.get("candidate_weight_delta"))
                evidence.append(evidence_row(
                    component_name=row.get("factor_or_strategy_id", "CANDIDATE_WEIGHT_UPDATE"),
                    component_type="POSITION_SIZING",
                    evidence_path="PROMOTION_READINESS",
                    source=path,
                    run_id=run_id,
                    metric_name="candidate_weight_delta",
                    metric_value=row.get("candidate_weight_delta"),
                    metric_unit="WEIGHT_DELTA",
                    status="NOT_USABLE",
                    reason="DRY_RUN_ZERO_DELTA_NOT_CERTIFIED_PERFORMANCE_EVIDENCE" if delta == 0 else "DRY_RUN_ONLY_NOT_BOUND_TO_CERTIFIED_PERFORMANCE_EVIDENCE",
                    usable=False,
                    coverage="UNUSABLE",
                ))
        elif "V20_82_BENCHMARK_STRATEGY_COMPARISON" in name:
            for row in rows:
                proxy = row.get("return_evidence_status", "") == PROXY_STATUS
                evidence.append(evidence_row(
                    component_name=row.get("strategy_name", "V20_82_STRATEGY"),
                    component_type="BENCHMARK_MODEL",
                    evidence_path="BENCHMARK_COMPARISON",
                    source=path,
                    run_id=run_id,
                    metric_name="strategy_return",
                    metric_value=row.get("strategy_return"),
                    metric_unit="RETURN_DECIMAL",
                    evaluation_window=row.get("evaluation_window", "NA"),
                    benchmark_name=row.get("benchmark_name", "NA"),
                    benchmark_return=row.get("benchmark_return"),
                    excess_return=row.get("excess_return"),
                    drawdown=row.get("strategy_max_drawdown"),
                    hit_rate=row.get("hit_rate_vs_benchmark"),
                    status="NOT_USABLE" if proxy else "CERTIFIED",
                    reason=PROXY_STATUS if proxy else "CERTIFIED_BENCHMARK_COMPARISON",
                    usable=not proxy,
                    coverage="UNUSABLE" if proxy else "FOUND",
                ))
        elif "V20_82_STRATEGY_MULTI_PATH_VALIDATION_TABLE" in name:
            for row in rows:
                proxy = row.get("return_evidence_status", "") == PROXY_STATUS
                etf_blocked = row.get("return_evidence_status", "") == "INSUFFICIENT_CERTIFIED_ETF_ROTATION_EVIDENCE"
                reason = PROXY_STATUS if proxy else row.get("return_evidence_status", "STRUCTURED_STRATEGY_VALIDATION")
                if etf_blocked:
                    reason = "INSUFFICIENT_CERTIFIED_ETF_ROTATION_EVIDENCE"
                evidence.append(evidence_row(
                    component_name=row.get("strategy_name", "V20_82_STRATEGY"),
                    component_type="BENCHMARK_MODEL",
                    evidence_path="BENCHMARK_COMPARISON",
                    source=path,
                    run_id=run_id,
                    metric_name="model_return",
                    metric_value=row.get("model_return"),
                    metric_unit="RETURN_DECIMAL",
                    evaluation_window=row.get("evaluation_window", "NA"),
                    benchmark_name="QQQ",
                    benchmark_return=row.get("benchmark_return"),
                    excess_return=row.get("excess_return"),
                    status="NOT_USABLE" if proxy or etf_blocked else "CERTIFIED",
                    reason=reason,
                    usable=not proxy and not etf_blocked,
                    coverage="UNUSABLE" if proxy or etf_blocked else "FOUND",
                ))
        elif "V20_82_ETF_ROTATION_SHADOW_SIGNAL_TABLE" in name or "V20_79A" in name:
            for row in rows:
                metric_value = row.get("rotation_shadow_score") or row.get("relative_strength_score") or row.get("coverage_ratio")
                component = row.get("etf_symbol") or row.get("ticker") or row.get("pair_group") or path.stem
                certified = has_exact_positive_etf_certification(row)
                evidence.append(evidence_row(
                    component_name=component,
                    component_type="ETF_ROTATION",
                    evidence_path="ETF_ROTATION_EVIDENCE",
                    source=path,
                    run_id=run_id,
                    metric_name="rotation_shadow_score",
                    metric_value=metric_value,
                    metric_unit="SCORE",
                    status="CERTIFIED" if certified else "NOT_USABLE",
                    reason="CERTIFIED_ETF_ROTATION_EVIDENCE" if certified else "INSUFFICIENT_CERTIFIED_ETF_ROTATION_EVIDENCE",
                    usable=certified,
                    coverage="FOUND" if certified else "UNUSABLE",
                ))
        usable_count = len([row for row in evidence[produced_before:] if row["usable_for_v20_82"] == "TRUE"])
        if produced_before != len(evidence) or fields:
            schema_valid = schema_valid_for(path, fields)
            add_audit(
                audit,
                input_family="STRUCTURED_EVIDENCE_INPUT",
                expected_stage=source_stage(path),
                candidate_file=path,
                detected_status="FOUND" if produced_before != len(evidence) else "UNUSED_STRUCTURED",
                row_count=len(rows),
                required_or_optional="OPTIONAL",
                schema_valid=schema_valid,
                semantic_valid=usable_count > 0,
                usable_count=usable_count,
                binding_quality="USABLE" if usable_count > 0 else "UNUSABLE",
                reject_reason="NA" if usable_count > 0 else ("NO_CERTIFIED_USABLE_METRIC_EXTRACTED" if schema_valid else "UNUSABLE_SCHEMA_IRRELEVANT_TO_CERTIFIED_EVIDENCE"),
            )
    return evidence, audit, unsafe


def required_paths_for(component_type: str) -> set[str]:
    if component_type == "FACTOR":
        return {"HISTORICAL_BACKTEST", "RANDOM_ASOF_BACKTEST", "LIVE_OBSERVATION"}
    if component_type == "ENTRY_STRATEGY":
        return {"HISTORICAL_BACKTEST", "RANDOM_ASOF_BACKTEST"}
    if component_type == "PORTFOLIO_MODEL":
        return {"PORTFOLIO_BACKTEST", "BENCHMARK_COMPARISON"}
    if component_type == "BENCHMARK_MODEL":
        return {"BENCHMARK_COMPARISON"}
    if component_type == "ETF_ROTATION":
        return {"ETF_ROTATION_EVIDENCE"}
    if component_type == "PROMOTION_GATE":
        return {"PROMOTION_READINESS"}
    return {"LIVE_OBSERVATION"}


def build_coverage(evidence: list[dict[str, str]]) -> list[dict[str, str]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in evidence:
        if row["coverage_status"] in {"FOUND", "UNUSABLE"}:
            grouped[(row["component_name"], row["component_type"])].append(row)
    coverage_rows: list[dict[str, str]] = []
    path_to_field = {
        "HISTORICAL_BACKTEST": "historical_backtest_found",
        "RANDOM_ASOF_BACKTEST": "random_asof_found",
        "LIVE_OBSERVATION": "live_observation_found",
        "REGIME_CONDITIONED": "regime_conditioned_found",
        "DOWNSIDE_RISK": "downside_risk_found",
        "PORTFOLIO_BACKTEST": "portfolio_backtest_found",
        "BENCHMARK_COMPARISON": "benchmark_comparison_found",
        "ETF_ROTATION_EVIDENCE": "etf_rotation_found",
    }
    for (component_name, component_type), rows in sorted(grouped.items()):
        usable_rows = [row for row in rows if row["usable_for_v20_82"] == "TRUE"]
        usable_paths = {row["evidence_path"] for row in usable_rows}
        required = required_paths_for(component_type)
        ratio = len(required.intersection(usable_paths)) / len(required) if required else 0.0
        fully_covered = ratio >= 1.0
        blocking = "NA" if fully_covered else "MISSING_OR_UNUSABLE_REQUIRED_EVIDENCE_PATHS"
        out = {
            "component_name": component_name,
            "component_type": component_type,
            "usable_evidence_count": str(len(usable_rows)),
            "required_evidence_count": str(len(required)),
            "evidence_coverage_ratio": f"{ratio:.6f}",
            "has_any_usable_evidence": tf(bool(usable_rows)),
            "v20_82_usable": tf(fully_covered),
            "blocking_reason": blocking,
        }
        for path_name, field in path_to_field.items():
            if path_name in usable_paths:
                out[field] = "FOUND"
            elif any(row["evidence_path"] == path_name for row in rows):
                out[field] = "UNUSABLE"
            else:
                out[field] = "MISSING"
        coverage_rows.append(out)
    if not coverage_rows:
        coverage_rows.append({
            "component_name": "NO_CERTIFIED_COMPONENT",
            "component_type": "LIVE_OBSERVATION",
            "historical_backtest_found": "MISSING",
            "random_asof_found": "MISSING",
            "live_observation_found": "MISSING",
            "regime_conditioned_found": "MISSING",
            "downside_risk_found": "MISSING",
            "portfolio_backtest_found": "MISSING",
            "benchmark_comparison_found": "MISSING",
            "etf_rotation_found": "MISSING",
            "usable_evidence_count": "0",
            "required_evidence_count": "1",
            "evidence_coverage_ratio": "0.000000",
            "has_any_usable_evidence": "FALSE",
            "v20_82_usable": "FALSE",
            "blocking_reason": "NO_USABLE_STRUCTURED_EVIDENCE",
        })
    return coverage_rows


def coverage_summary(coverage_rows: list[dict[str, str]]) -> dict[str, object]:
    field_names = [
        "historical_backtest_found",
        "random_asof_found",
        "live_observation_found",
        "regime_conditioned_found",
        "downside_risk_found",
        "portfolio_backtest_found",
        "benchmark_comparison_found",
        "etf_rotation_found",
    ]
    summary: dict[str, object] = {
        "component_count": len(coverage_rows),
        "v20_82_usable_component_count": sum(row["v20_82_usable"] == "TRUE" for row in coverage_rows),
    }
    for field in field_names:
        values = [row[field] for row in coverage_rows]
        if any(value == "FOUND" for value in values):
            status = "FOUND"
        elif any(value == "UNUSABLE" for value in values):
            status = "UNUSABLE"
        else:
            status = "MISSING"
        summary[field.replace("_found", "")] = status
    return summary


def write_report(status: str, evidence: list[dict[str, str]], audit: list[dict[str, str]], coverage: list[dict[str, str]], summary: dict[str, object]) -> None:
    usable_count = sum(row["usable_for_v20_82"] == "TRUE" for row in evidence)
    fully_covered_count = sum(row["v20_82_usable"] == "TRUE" for row in coverage)
    rejected = [row for row in evidence if row["usable_for_v20_82"] != "TRUE"]
    lines = [
        "# V20.84 Certified Multi-Path Evidence Export Report",
        "## Status",
        f"- status: {status}",
        f"- usable_evidence_count: {usable_count}",
        "## Research-Only Guardrail",
        "- research_only: TRUE",
        "- official_recommendation_created: FALSE",
        "- official_weight_mutated: FALSE",
        "- trade_action_created: FALSE",
        "## Required Evidence Rerun Counts",
        f"- readable_regime_evidence_count: {summary.get('readable_regime_evidence_count', 0)}",
        f"- readable_downside_risk_evidence_count: {summary.get('readable_downside_risk_evidence_count', 0)}",
        f"- readable_benchmark_comparison_evidence_count: {summary.get('readable_benchmark_comparison_evidence_count', 0)}",
        f"- readable_acceptance_proof_evidence_count: {summary.get('readable_acceptance_proof_evidence_count', 0)}",
        f"- readable_ranking_delta_diagnostic_evidence_count: {summary.get('readable_ranking_delta_diagnostic_evidence_count', 0)}",
        f"- missing_required_evidence_categories: {'|'.join(summary.get('missing_required_evidence_categories', [])) if summary.get('missing_required_evidence_categories') else 'NONE'}",
        "- promotion_allowed: FALSE",
        "- nasdaq_hurdle_passed: FALSE",
        "## Input Binding Summary",
        f"- audited_inputs: {len(audit)}",
        f"- usable_input_bindings: {sum(int(row['usable_evidence_count']) > 0 for row in audit)}",
        "## Certified Evidence Summary",
        f"- certified_rows: {usable_count}",
        f"- row_level_usable_evidence_exists: {tf(usable_count > 0)}",
        f"- fully_covered_v20_82_components_exist: {tf(fully_covered_count > 0)}",
        "- proxy_returns_counted_as_certified_alpha: FALSE",
        "- etf_evidence_counted_without_certified_rotation_backtest: FALSE",
        "## Rejected / Unusable Evidence",
        f"- rejected_or_unusable_rows: {len(rejected)}",
        "- generic manifests, required output checks, hash ledgers, readable reports, status summaries, and diagnostics do not increase coverage.",
        "## Component Evidence Coverage",
    ]
    for key in [
        "historical_backtest",
        "random_asof",
        "live_observation",
        "regime_conditioned",
        "downside_risk",
        "portfolio_backtest",
        "benchmark_comparison",
        "etf_rotation",
    ]:
        lines.append(f"- {key}: {summary.get(key, 'MISSING')}")
    lines.extend([
        "## V20.82 Integration Notes",
        "- V20.82 may inspect row-level usable evidence, but row-level evidence alone does not clear multi-path component coverage.",
        "- V20.82 should remain blocked/partial when no component satisfies required multi-path coverage.",
        "- V20.84-R2 consumes V20.89 required evidence paths and V20.82-R5 category validation detail.",
        "- Required missing paths block at path-level integration; optional WARN paths do not block final R2 status.",
        "- Rows marked PROXY_TECHNICAL_RETURN_NOT_CERTIFIED_STRATEGY_ALPHA are explicitly non-usable.",
        "- ETF rows remain non-usable unless certified ETF rotation/backtest evidence is present.",
        "## Next Development Recommendation",
        "- Add certified ETF rotation backtest evidence and fill missing regime/downside paths before promotion-oriented use.",
        "",
    ])
    OUTPUTS["report"].parent.mkdir(parents=True, exist_ok=True)
    OUTPUTS["report"].write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    run_id = make_run_id()
    created_at = now_utc()
    evidence, audit, unsafe = collect_evidence(run_id)
    coverage = build_coverage(evidence)
    summary = coverage_summary(coverage)
    r2_detail, r2_status, r2_meta = build_r2_integration_detail()
    summary.update({
        "readable_regime_evidence_count": r2_meta["readable_regime_evidence_count"],
        "readable_downside_risk_evidence_count": r2_meta["readable_downside_risk_evidence_count"],
        "readable_benchmark_comparison_evidence_count": r2_meta["readable_benchmark_comparison_evidence_count"],
        "readable_acceptance_proof_evidence_count": r2_meta["readable_acceptance_proof_evidence_count"],
        "readable_ranking_delta_diagnostic_evidence_count": r2_meta["readable_ranking_delta_diagnostic_evidence_count"],
        "missing_required_evidence_categories": r2_meta["missing_required_evidence_categories"],
    })
    usable_count = sum(row["usable_for_v20_82"] == "TRUE" for row in evidence)
    fully_covered_count = sum(row["v20_82_usable"] == "TRUE" for row in coverage)
    partial_component_count = sum(row["has_any_usable_evidence"] == "TRUE" and row["v20_82_usable"] != "TRUE" for row in coverage)
    if fully_covered_count == 0:
        integration_status = "PARTIAL_BLOCK_MISSING_REQUIRED_PATHS"
    elif partial_component_count > 0:
        integration_status = "PARTIAL_PASS_WITH_COMPONENT_GAPS"
    else:
        integration_status = "FULL_COMPONENT_COVERAGE_AVAILABLE"
    has_gaps = any(row["v20_82_usable"] != "TRUE" for row in coverage) or any(
        value in {"MISSING", "UNUSABLE"} for key, value in summary.items() if key.endswith(("backtest", "comparison", "rotation", "observation", "conditioned", "risk"))
    )
    if unsafe:
        status = UNSAFE_STATUS
    elif usable_count == 0:
        status = NO_EVIDENCE_STATUS
    elif has_gaps:
        status = GAPS_STATUS
    else:
        status = PASS_STATUS
    status = r2_status

    write_csv(OUTPUTS["evidence"], EVIDENCE_FIELDS, evidence)
    write_csv(OUTPUTS["audit"], AUDIT_FIELDS, audit)
    write_csv(OUTPUTS["coverage"], COVERAGE_FIELDS, coverage)
    write_csv(R2_DETAIL, R2_DETAIL_FIELDS, r2_detail)
    R2_DETAIL_ALIAS.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(R2_DETAIL, R2_DETAIL_ALIAS)
    write_report(status, evidence, audit, coverage, summary)
    input_files = sorted(
        {
            row["source_file"] for row in evidence
        }
        | {
            rel(V20_89_REQUIRED_EVIDENCE_MANIFEST),
            rel(V20_82_R5_DETAIL),
            rel(V20_90_ETF_ROTATION_EVIDENCE),
            rel(V20_91_MULTI_WINDOW_STRATEGY_EVIDENCE),
        }
        | {row["bound_source_file"] for row in r2_detail if row["bound_source_file"] != "NA"}
    )
    manifest = {
        "stage": STAGE,
        "run_id": run_id,
        "created_at_utc": created_at,
        "status": status,
        "input_files": input_files,
        "output_files": {key: rel(path) for key, path in OUTPUTS.items()} | {"r2_detail": rel(R2_DETAIL)},
        "row_counts": {
            "evidence": len(evidence),
            "audit": len(audit),
            "coverage": len(coverage),
            "r2_detail": len(r2_detail),
        },
        "r2_final_status": r2_status,
        **r2_meta,
        "usable_evidence_count": usable_count,
        "row_level_usable_evidence_count": usable_count,
        "v20_82_fully_covered_component_count": fully_covered_count,
        "v20_82_partial_component_count": partial_component_count,
        "v20_82_integration_status": integration_status,
        "coverage_summary": summary,
        "promotion_allowed": False,
        "nasdaq_hurdle_passed": False,
        "research_only": True,
        "official_recommendation_created": False,
        "official_weight_mutated": False,
        "trade_action_created": False,
    }
    OUTPUTS["manifest"].parent.mkdir(parents=True, exist_ok=True)
    OUTPUTS["manifest"].write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for source, alias in ALIASES.items():
        alias.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, alias)

    print(status)
    print(f"RUN_ID={run_id}")
    print(f"R2_INTEGRATION_CATEGORY_COUNT={r2_meta['integration_category_count']}")
    print(f"R2_INTEGRATED_CATEGORY_COUNT={r2_meta['integrated_category_count']}")
    print(f"R2_BLOCKED_CATEGORY_COUNT={r2_meta['blocked_category_count']}")
    print(f"R2_WARNED_CATEGORY_COUNT={r2_meta['warned_category_count']}")
    print(f"USABLE_EVIDENCE_COUNT={usable_count}")
    print(f"READABLE_REGIME_EVIDENCE_COUNT={r2_meta['readable_regime_evidence_count']}")
    print(f"READABLE_DOWNSIDE_RISK_EVIDENCE_COUNT={r2_meta['readable_downside_risk_evidence_count']}")
    print(f"READABLE_BENCHMARK_COMPARISON_EVIDENCE_COUNT={r2_meta['readable_benchmark_comparison_evidence_count']}")
    print(f"READABLE_ACCEPTANCE_PROOF_EVIDENCE_COUNT={r2_meta['readable_acceptance_proof_evidence_count']}")
    print(f"READABLE_RANKING_DELTA_DIAGNOSTIC_EVIDENCE_COUNT={r2_meta['readable_ranking_delta_diagnostic_evidence_count']}")
    print(f"MISSING_REQUIRED_EVIDENCE_CATEGORIES={'|'.join(r2_meta['missing_required_evidence_categories']) if r2_meta['missing_required_evidence_categories'] else 'NONE'}")
    print("PROMOTION_ALLOWED=FALSE")
    print("NASDAQ_HURDLE_PASSED=FALSE")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("OFFICIAL_WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    return 1 if status.startswith("BLOCKED_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
